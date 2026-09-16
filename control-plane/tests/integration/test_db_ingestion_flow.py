"""T017: Integration test for quickstart Scenarios 1-3 (US1, FR-002/FR-003).

Register + test a PostgreSQL source (schema discovered), configure customer
(incremental, cursor updated_at) + orders (full), run the pipeline, verify
Bronze batches + metadata, and confirm a second incremental run ingests only
the delta with zero duplicates.

Runs are driven directly through the ingestion engine (``process_ingestion_run``
fixture) and batches inspected via the DB, since the pipelines/runs/batches API
routers land in later phases (US4).
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.ingestion.gateway import SimTable


def _seed_platform(app):
    from datafoundry.controlplane.db.models import (
        EnvironmentType,
        Platform,
        Provider,
    )

    with app.state.sessionmaker() as sess:
        platform = Platform(
            name="crm-platform",
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
        "name": "crm-prod",
        "type": "postgres",
        "config": {
            "host": "crm.internal",
            "port": 5432,
            "database": "crm",
            "credentials": {"secretRef": "crm-ro-user"},
        },
    }
    response = client.post("/api/v1/sources", json=body)
    assert response.status_code == 201, response.text
    return response.json()["source_id"]


_CUSTOMER_COLUMNS = [
    {"name": "customer_id", "type": "integer", "nullable": False},
    {"name": "email", "type": "string", "nullable": False},
    {"name": "updated_at", "type": "timestamp", "nullable": False},
]
_ORDERS_COLUMNS = [
    {"name": "order_id", "type": "integer", "nullable": False},
    {"name": "customer_id", "type": "integer", "nullable": False},
]


def _seed_source_data(app, source_id):
    """Seed customer (incremental) + orders (full) with a large-ish dataset."""
    app.state.source_gateway.seed_database(
        str(source_id),
        source_type="postgres",
        tables={
            "customer": SimTable(name="customer", columns=_CUSTOMER_COLUMNS),
            "orders": SimTable(name="orders", columns=_ORDERS_COLUMNS),
        },
    )
    # 1M customer rows (SC-005 scale) + a few orders.
    customers = [
        {
            "customer_id": i,
            "email": f"user{i}@example.com",
            "updated_at": f"2026-09-{1 + (i % 28):02d}",
        }
        for i in range(1, 1_000_001)
    ]
    app.state.source_gateway.add_table(
        str(source_id), SimTable(name="customer", columns=_CUSTOMER_COLUMNS), rows=customers
    )
    app.state.source_gateway.add_table(
        str(source_id),
        SimTable(name="orders", columns=_ORDERS_COLUMNS),
        rows=[{"order_id": i, "customer_id": i} for i in range(1, 101)],
    )


def _valid_config():
    return {
        "apiVersion": "datafoundry/v1",
        "kind": "IngestionConfig",
        "metadata": {"name": "crm-to-bronze", "source": "crm-prod"},
        "source": {
            "type": "postgres",
            "objects": [
                {"name": "customer", "mode": "incremental", "cursor_column": "updated_at"},
                {"name": "orders", "mode": "full"},
            ],
        },
        "schedule": "every 15 minutes",
        "target": {"zone": "bronze"},
        "validation": {"reconciliation_tolerance": 0, "contract_mode": "enforce"},
    }


def _queue_run(app, pipeline_id):
    """Create a queued IngestionRun for a pipeline directly (US4 API lands later)."""
    from datafoundry.controlplane.db.models import IngestionRun, RunTrigger

    with app.state.sessionmaker() as sess:
        run = IngestionRun(pipeline_id=pipeline_id, trigger=RunTrigger.manual)
        sess.add(run)
        sess.commit()
        return run.id


def _batches(app, run_id):
    """Return {source_object: batch} for a run."""
    from datafoundry.controlplane.db.models import IngestionBatch

    with app.state.sessionmaker() as sess:
        rows = sess.query(IngestionBatch).filter(IngestionBatch.run_id == run_id).all()
        return {b.source_object: b for b in rows}


class TestScenario123DbIngestion:
    def test_register_test_configure_run(self, app, client, process_ingestion_run):
        # Scenario 1: register + test (schema discovered).
        source_id = _register_source(app, client)
        _seed_source_data(app, source_id)
        test = client.post(f"/api/v1/sources/{source_id}/test")
        assert test.status_code == 200
        assert test.json()["ok"] is True
        objects = {o["object"] for o in test.json()["discovered_schema"]}
        assert objects == {"customer", "orders"}

        # Scenario 2: configure -> pipeline auto-created.
        config = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        assert config.status_code == 201, config.text
        body = config.json()
        pipeline_id = uuid.UUID(body["pipeline_id"])

        # First run: drive the engine directly.
        run_id = _queue_run(app, pipeline_id)
        process_ingestion_run(run_id)

        batches = _batches(app, run_id)
        assert set(batches) == {"customer", "orders"}
        assert batches["customer"].status.value == "ingestion_validated"
        assert batches["customer"].record_count == 1_000_000
        assert batches["orders"].status.value == "ingestion_validated"
        assert batches["orders"].record_count == 100

        # Batch metadata carries full context (FR-008).
        meta = batches["customer"].metadata_json
        assert meta["source_system"] == "crm-prod"
        assert meta["source_object"] == "customer"
        assert meta["ingestion_date"]
        assert meta["pipeline_id"] == str(pipeline_id)
        assert meta["record_count"] == 1_000_000
        assert meta["status"] == "ingestion_validated"

        # Contracts inferred on first run, pending (US3-AC3).
        from datafoundry.controlplane.db.models import ApprovalStatus, SourceContract

        with app.state.sessionmaker() as sess:
            contracts = sess.query(SourceContract).filter_by(source_id=uuid.UUID(source_id)).all()
        assert {c.object_name for c in contracts} == {"customer", "orders"}
        assert all(c.approval_status == ApprovalStatus.pending for c in contracts)

        # Scenario 3: second run ingests only the delta (zero duplicates).
        # Advance the source: add rows with a newer updated_at.
        app.state.source_gateway.add_table(
            str(source_id),
            SimTable(name="customer", columns=_CUSTOMER_COLUMNS),
            rows=[
                {"customer_id": 1_000_001, "email": "new@example.com", "updated_at": "2026-10-01"},
                {"customer_id": 1_000_002, "email": "new2@example.com", "updated_at": "2026-10-02"},
            ],
        )

        run2_id = _queue_run(app, pipeline_id)
        process_ingestion_run(run2_id)
        batches2 = _batches(app, run2_id)
        # Only the delta (2 new rows) ingested — zero duplicates (R-06, SC-005).
        assert batches2["customer"].record_count == 2
        assert batches2["orders"].record_count == 100
