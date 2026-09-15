"""T028: Integration test for quickstart Scenario 3 (US3, FR-008/FR-009/FR-010).

Ingest a batch with known bad records, verify quarantine entries with full
context, fix the cause, replay, verify no duplicates + removal from active
queue, verify retention-expired replay refused.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta


def _seed_dataset(app, name="customer", owner="dev@datafoundry.local"):
    from datafoundry.controlplane.db.models import (
        DataClassification,
        Dataset,
        DatasetLayer,
    )

    with app.state.sessionmaker() as sess:
        ds = Dataset(
            name=name,
            layer=DatasetLayer.silver,
            schema_definition={"customer_id": {"type": "integer", "nullable": False}},
            owner_identity=owner,
            classification=DataClassification.internal,
        )
        sess.add(ds)
        sess.commit()
        return ds.id


def _quarantine(app, ds_id, *, batch_id, payload_ref, failure_reason, failed_test, meta):
    """Write a quarantine entry via the gateway + persist the DB row."""
    from datafoundry.controlplane.db.models import QuarantineEntry

    ref = app.state.quality_gateway.write_quarantine(
        dataset_id=str(ds_id),
        batch_id=str(batch_id),
        payload_ref=payload_ref,
        meta=meta,
    )
    with app.state.sessionmaker() as sess:
        entry = QuarantineEntry(
            dataset_id=ds_id,
            batch_id=batch_id,
            payload_ref=ref,
            failure_reason=failure_reason,
            failed_test=failed_test,
            attempt_count=1,
            replay_eligible=True,
            retention_expiry=datetime.now(UTC) + timedelta(days=30),
            metadata_json=meta,
        )
        sess.add(entry)
        sess.commit()
        return entry.id


class TestScenario3QuarantineReplay:
    def test_quarantine_replay_flow(self, app, client):
        ds_id = _seed_dataset(app)
        batch_id = uuid.uuid4()
        meta = {"source": "sap", "pipeline_id": "pipeline-1", "error_details": {"code": "E_DUP"}}

        # Ingest a batch with known bad records -> quarantine entries.
        entry_id = _quarantine(
            app,
            ds_id,
            batch_id=batch_id,
            payload_ref="s3://bucket/quarantine/rec-1.parquet",
            failure_reason="duplicate customer_id",
            failed_test="uniqueness_customer_id",
            meta=meta,
        )

        # Verify each appears with full context (FR-008, US3-AC1).
        listing = client.get(f"/api/v1/datasets/{ds_id}/quarantine")
        assert listing.status_code == 200
        items = listing.json()["items"]
        assert len(items) == 1
        assert items[0]["payload_ref"] == "s3://bucket/quarantine/rec-1.parquet"
        assert items[0]["failure_reason"] == "duplicate customer_id"
        assert items[0]["failed_test"] == "uniqueness_customer_id"
        assert items[0]["batch_id"] == str(batch_id)
        assert items[0]["replay_eligible"] is True

        # Filter by source / pipeline / batch / reason (US3-AC3).
        assert (
            len(
                client.get(f"/api/v1/datasets/{ds_id}/quarantine", params={"source": "sap"}).json()[
                    "items"
                ]
            )
            == 1
        )
        assert (
            len(
                client.get(
                    f"/api/v1/datasets/{ds_id}/quarantine",
                    params={"pipeline_id": "pipeline-1"},
                ).json()["items"]
            )
            == 1
        )
        assert (
            len(
                client.get(
                    f"/api/v1/datasets/{ds_id}/quarantine",
                    params={"batch_id": str(batch_id)},
                ).json()["items"]
            )
            == 1
        )
        assert (
            len(
                client.get(
                    f"/api/v1/datasets/{ds_id}/quarantine",
                    params={"failure_reason": "duplicate"},
                ).json()["items"]
            )
            == 1
        )

        # Fix the cause, then replay (FR-009, US3-AC2).
        replay = client.post(f"/api/v1/quarantine/{entry_id}/replay")
        assert replay.status_code == 202, replay.text
        replay_run_id = replay.json()["replay_run_id"]
        uuid.UUID(replay_run_id)

        # Successful replay removes from active queue (no duplicates).
        after = client.get(f"/api/v1/datasets/{ds_id}/quarantine").json()["items"]
        assert len(after) == 0

    def test_replay_after_retention_expiry_refused(self, app, client):
        ds_id = _seed_dataset(app)
        batch_id = uuid.uuid4()
        meta = {"source": "sap", "pipeline_id": "pipeline-1"}

        from datafoundry.controlplane.db.models import QuarantineEntry

        ref = app.state.quality_gateway.write_quarantine(
            dataset_id=str(ds_id),
            batch_id=str(batch_id),
            payload_ref="s3://bucket/quarantine/expired.parquet",
            meta=meta,
        )
        with app.state.sessionmaker() as sess:
            entry = QuarantineEntry(
                dataset_id=ds_id,
                batch_id=batch_id,
                payload_ref=ref,
                failure_reason="stale data",
                failed_test="freshness",
                attempt_count=1,
                replay_eligible=True,
                retention_expiry=datetime.now(UTC) - timedelta(days=1),
                metadata_json=meta,
            )
            sess.add(entry)
            sess.commit()
            entry_id = entry.id

        # Replay after retention_expiry refused 409 (FR-010).
        response = client.post(f"/api/v1/quarantine/{entry_id}/replay")
        assert response.status_code == 409
        assert response.json()["code"] == "retention_expired"

    def test_replay_not_eligible_refused(self, app, client):
        ds_id = _seed_dataset(app)
        batch_id = uuid.uuid4()
        meta = {"source": "sap", "pipeline_id": "pipeline-1"}

        from datafoundry.controlplane.db.models import QuarantineEntry

        ref = app.state.quality_gateway.write_quarantine(
            dataset_id=str(ds_id),
            batch_id=str(batch_id),
            payload_ref="s3://bucket/quarantine/not-eligible.parquet",
            meta=meta,
        )
        with app.state.sessionmaker() as sess:
            entry = QuarantineEntry(
                dataset_id=ds_id,
                batch_id=batch_id,
                payload_ref=ref,
                failure_reason="duplicate",
                failed_test="uniqueness",
                attempt_count=1,
                replay_eligible=False,
                retention_expiry=datetime.now(UTC) + timedelta(days=30),
                metadata_json=meta,
            )
            sess.add(entry)
            sess.commit()
            entry_id = entry.id

        response = client.post(f"/api/v1/quarantine/{entry_id}/replay")
        assert response.status_code == 409
        assert response.json()["code"] == "not_eligible"
