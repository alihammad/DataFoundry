"""T026: Integration test for quickstart Scenario 4 (US2, FR-006/FR-007).

Drop valid and deliberately corrupted Parquet files into a watched object
storage location, run ingestion, and verify:
- valid files land in Bronze with file-level metadata (name, size, checksum,
  ingestion timestamp);
- a corrupted file routes to quarantine with a failure reason;
- valid files are still ingested (partial success, US2-AC2);
- run outcome is ``partial``;
- a duplicate checksum is detected and not double-loaded (US2-AC3).

Runs are driven directly through the ingestion engine (``process_ingestion_run``
fixture) and batches/quarantine inspected via the DB, since the pipelines/runs
API routers land in later phases (US4).
"""

from __future__ import annotations

import uuid

import pyarrow as pa
import pyarrow.parquet as pq


def _seed_platform(app):
    from datafoundry.controlplane.db.models import (
        EnvironmentType,
        Platform,
        Provider,
    )

    with app.state.sessionmaker() as sess:
        platform = Platform(
            name="events-platform",
            provider=Provider.aws,
            cloud_scope_id="scope-1",
            region="us-east-1",
            environment_type=EnvironmentType.test,
            owner_identity="dev@datafoundry.local",
        )
        sess.add(platform)
        sess.commit()
        return platform.id


def _register_source(app, client):
    platform_id = _seed_platform(app)
    body = {
        "platform_id": str(platform_id),
        "name": "events-drop",
        "type": "object_storage",
        "config": {"location": "s3://acme-landing/events", "format": "parquet"},
    }
    response = client.post("/api/v1/sources", json=body)
    assert response.status_code == 201, response.text
    return response.json()["source_id"]


def _parquet_bytes(rows: list[dict]) -> bytes:
    table = pa.Table.from_pylist(rows)
    buf = pa.BufferOutputStream()
    pq.write_table(table, buf)
    return buf.getvalue().to_pybytes()


def _valid_config():
    return {
        "apiVersion": "datafoundry/v1",
        "kind": "IngestionConfig",
        "metadata": {"name": "events-to-bronze", "source": "events-drop"},
        "source": {
            "type": "object_storage",
            "filePattern": "s3://acme-landing/events/*.parquet",
        },
        "schedule": "every 15 minutes",
        "target": {"zone": "bronze"},
        "validation": {"reconciliation_tolerance": 0, "contract_mode": "enforce"},
    }


def _queue_run(app, pipeline_id):
    from datafoundry.controlplane.db.models import IngestionRun, RunTrigger

    with app.state.sessionmaker() as sess:
        run = IngestionRun(pipeline_id=pipeline_id, trigger=RunTrigger.manual)
        sess.add(run)
        sess.commit()
        return run.id


def _batches(app, run_id):
    from datafoundry.controlplane.db.models import IngestionBatch

    with app.state.sessionmaker() as sess:
        rows = sess.query(IngestionBatch).filter(IngestionBatch.run_id == run_id).all()
        return {b.source_object: b for b in rows}


def _quarantine_records(app):
    from datafoundry.controlplane.db.models import QuarantineRecord

    with app.state.sessionmaker() as sess:
        return sess.query(QuarantineRecord).all()


class TestScenario4FileIngestion:
    def test_valid_and_corrupt_files_partial_and_duplicate(
        self, app, client, process_ingestion_run
    ):
        # Scenario 4: register object-storage source + configure.
        source_id = _register_source(app, client)
        config = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        assert config.status_code == 201, config.text
        pipeline_id = uuid.UUID(config.json()["pipeline_id"])

        # Seed the object-storage source: two valid files + one corrupted.
        valid_a = _parquet_bytes([{"event_id": 1, "name": "a"}, {"event_id": 2, "name": "b"}])
        valid_b = _parquet_bytes([{"event_id": 3, "name": "c"}])
        app.state.source_gateway.seed_object_storage(str(source_id))
        app.state.source_gateway.add_file(
            str(source_id), "events_a.parquet", valid_a, fmt="parquet"
        )
        app.state.source_gateway.add_file(
            str(source_id), "events_b.parquet", valid_b, fmt="parquet"
        )
        app.state.source_gateway.add_file(
            str(source_id), "corrupt.parquet", b"not-a-valid-parquet", fmt="parquet"
        )

        # First run: valid files land, corrupt file quarantined (partial).
        run_id = _queue_run(app, pipeline_id)
        run = process_ingestion_run(run_id)

        assert run.outcome.value == "partial"
        batches = _batches(app, run_id)
        assert set(batches) == {"events_a.parquet", "events_b.parquet", "corrupt.parquet"}
        assert batches["events_a.parquet"].status.value == "ingestion_validated"
        assert batches["events_b.parquet"].status.value == "ingestion_validated"
        assert batches["corrupt.parquet"].status.value == "quarantined"

        # File-level metadata on valid batches (FR-008, US2-AC1).
        meta = batches["events_a.parquet"].metadata_json
        assert meta["file"]["name"] == "events_a.parquet"
        assert meta["file"]["size"] == len(valid_a)
        assert meta["file"]["checksum"]
        assert meta["file"]["ingestion_timestamp"]
        assert batches["events_a.parquet"].checksum

        # Quarantine record written for the corrupt file (FR-006, US2-AC2).
        records = _quarantine_records(app)
        assert len(records) == 1
        assert records[0].payload_ref == "corrupt.parquet"
        assert records[0].failed_check == "format"
        assert records[0].failure_reason

        # GET /quarantine lists the record (T030).
        q = client.get("/api/v1/quarantine")
        assert q.status_code == 200
        items = q.json()["items"]
        assert len(items) == 1
        assert items[0]["failed_check"] == "format"
        assert items[0]["source_object"] == "corrupt.parquet"

        # Second run: re-deliver the same valid file (identical checksum) ->
        # duplicate detected, not double-loaded (FR-007, US2-AC3).
        app.state.source_gateway.seed_object_storage(str(source_id))
        app.state.source_gateway.add_file(
            str(source_id), "events_a.parquet", valid_a, fmt="parquet"
        )
        run2_id = _queue_run(app, pipeline_id)
        process_ingestion_run(run2_id)
        batches2 = _batches(app, run2_id)
        assert batches2["events_a.parquet"].status.value == "quarantined"
        assert batches2["events_a.parquet"].metadata_json["failed_check"] == "checksum"
        assert "duplicate" in batches2["events_a.parquet"].metadata_json["failure_reason"]

        # The duplicate is recorded in quarantine, not double-loaded.
        records2 = _quarantine_records(app)
        assert len(records2) == 2
        assert any(r.failed_check == "checksum" for r in records2)
