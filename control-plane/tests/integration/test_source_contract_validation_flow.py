"""T032: Integration test for quickstart Scenario 5 (US3, FR-009/FR-010/FR-020).

Approve an inferred source contract, mutate the source schema (integer ->
string), run the pipeline, and verify:
- the change is classified ``breaking``;
- the batch is ``ingested`` but NOT ``ingestion_validated`` (promotion blocked);
- an alert is raised naming the offending column/change;
- reconciliation reports a difference when counts diverge.
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.ingestion.gateway import SimTable

_COLUMNS = [
    {"name": "customer_id", "type": "integer", "nullable": False},
    {"name": "email", "type": "string", "nullable": False},
]


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


def _valid_config():
    return {
        "apiVersion": "datafoundry/v1",
        "kind": "IngestionConfig",
        "metadata": {"name": "crm-to-bronze", "source": "crm-prod"},
        "source": {
            "type": "postgres",
            "objects": [{"name": "customer", "mode": "full"}],
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


class TestScenario5ContractValidation:
    def test_breaking_change_blocks_promotion_and_alerts(self, app, client, process_ingestion_run):
        from datafoundry.controlplane.db.models import (
            ApprovalStatus,
            AuditRecord,
            BatchStatus,
            IngestionBatch,
            SourceContract,
        )

        source_id = _register_source(app, client)

        # Seed source with integer customer_id.
        app.state.source_gateway.seed_database(
            str(source_id),
            source_type="postgres",
            tables={"customer": SimTable(name="customer", columns=_COLUMNS)},
        )
        app.state.source_gateway.add_table(
            str(source_id),
            SimTable(name="customer", columns=_COLUMNS),
            rows=[
                {"customer_id": 1, "email": "a@example.com"},
                {"customer_id": 2, "email": "b@example.com"},
            ],
        )

        # Configure -> pipeline auto-created.
        config = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        assert config.status_code == 201, config.text
        pipeline_id = uuid.UUID(config.json()["pipeline_id"])

        # First run: contract inferred, pending.
        run1 = _queue_run(app, pipeline_id)
        process_ingestion_run(run1)
        with app.state.sessionmaker() as sess:
            contract = (
                sess.query(SourceContract)
                .filter_by(source_id=uuid.UUID(source_id), object_name="customer")
                .one()
            )
            contract_id = contract.id
            assert contract.approval_status == ApprovalStatus.pending

        # Approve the inferred contract (owner authorisation).
        approve = client.post(f"/api/v1/contracts/{contract_id}/approve", json={})
        assert approve.status_code == 200, approve.text
        assert approve.json() == {"approval_status": "approved"}

        # Mutate the source schema: customer_id integer -> string (breaking).
        app.state.source_gateway.add_table(
            str(source_id),
            SimTable(
                name="customer",
                columns=[
                    {"name": "customer_id", "type": "string", "nullable": False},
                    {"name": "email", "type": "string", "nullable": False},
                ],
            ),
            rows=[
                {"customer_id": "1", "email": "a@example.com"},
                {"customer_id": "2", "email": "b@example.com"},
            ],
        )

        # Second run: breaking change blocks promotion.
        run2 = _queue_run(app, pipeline_id)
        process_ingestion_run(run2)

        with app.state.sessionmaker() as sess:
            batch = sess.query(IngestionBatch).filter_by(run_id=run2).one()
            assert batch.status == BatchStatus.ingested
            assert batch.metadata_json["status"] == "ingested"
            violations = batch.metadata_json["contract_violations"]
            breaking = [v for v in violations if v["classification"] == "breaking"]
            assert breaking, violations
            assert breaking[0]["column"] == "customer_id"
            assert breaking[0]["change"] == "type_change"

            # Alert raised naming the offending column/change.
            alerts = (
                sess.query(AuditRecord).filter_by(action="ingestion.alert.breaking_change").all()
            )
            assert alerts, "expected a breaking-change alert"
            payload = alerts[-1].payload
            assert payload["object_name"] == "customer"
            assert payload["violations"][0]["column"] == "customer_id"

    def test_reconciliation_failure_blocks_promotion(self, app, client, process_ingestion_run):
        from datafoundry.controlplane.db.models import (
            AuditRecord,
            BatchStatus,
            IngestionBatch,
        )

        source_id = _register_source(app, client)
        app.state.source_gateway.seed_database(
            str(source_id),
            source_type="postgres",
            tables={"customer": SimTable(name="customer", columns=_COLUMNS)},
        )
        app.state.source_gateway.add_table(
            str(source_id),
            SimTable(name="customer", columns=_COLUMNS),
            rows=[
                {"customer_id": 1, "email": "a@example.com"},
                {"customer_id": 2, "email": "b@example.com"},
            ],
        )

        config = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        assert config.status_code == 201, config.text
        pipeline_id = uuid.UUID(config.json()["pipeline_id"])

        # Simulate a count mismatch: gateway reports far more rows than ingested.
        app.state.source_gateway.count_rows = lambda source_id, *, object_name: 1_000_000

        run_id = _queue_run(app, pipeline_id)
        process_ingestion_run(run_id)

        with app.state.sessionmaker() as sess:
            batch = sess.query(IngestionBatch).filter_by(run_id=run_id).one()
            assert batch.status == BatchStatus.ingested
            assert batch.metadata_json["status"] == "ingested"
            assert batch.metadata_json["reconciliation"]["ok"] is False

            alerts = (
                sess.query(AuditRecord)
                .filter_by(action="ingestion.alert.reconciliation_failure")
                .all()
            )
            assert alerts, "expected a reconciliation alert"
            assert alerts[-1].payload["difference"] == 999_998
