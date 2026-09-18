"""T039: Integration test for quickstart Scenario 6 (US4, FR-011/FR-013/FR-014).

Manual trigger -> run executes and appears in history; force failure -> retry
re-processes only what's needed with no duplicates; pause -> schedule elapses
with no run started; resume -> runs resume.

The pipelines/runs API (US4) drives runs through the ingestion dispatcher; in
tests the dispatcher is a no-op so runs are executed explicitly via
``process_ingestion_run``. The scheduler is exercised directly via
``IngestionScheduler.tick()``.
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


def _seed_source_data(app, source_id):
    app.state.source_gateway.seed_database(
        str(source_id),
        source_type="postgres",
        tables={"customer": SimTable(name="customer", columns=_CUSTOMER_COLUMNS)},
    )
    customers = [
        {
            "customer_id": i,
            "email": f"user{i}@example.com",
            "updated_at": f"2026-09-{1 + (i % 28):02d}",
        }
        for i in range(1, 1001)
    ]
    app.state.source_gateway.add_table(
        str(source_id), SimTable(name="customer", columns=_CUSTOMER_COLUMNS), rows=customers
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
            ],
        },
        "schedule": "every 15 minutes",
        "target": {"zone": "bronze"},
        "validation": {"reconciliation_tolerance": 0, "contract_mode": "enforce"},
    }


def _make_pipeline(app, client):
    source_id = _register_source(app, client)
    _seed_source_data(app, source_id)
    response = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["pipeline_id"]), source_id


def _run_status(app, run_id):
    from datafoundry.controlplane.db.models import IngestionRun

    with app.state.sessionmaker() as sess:
        return sess.get(IngestionRun, run_id).status.value


class TestScenario6PipelineOperations:
    def test_manual_trigger_history_and_retry(self, app, client, process_ingestion_run):
        pipeline_id, source_id = _make_pipeline(app, client)

        # Manual trigger -> 202; run executes and appears in history.
        trigger = client.post(f"/api/v1/pipelines/{pipeline_id}/run")
        assert trigger.status_code == 202, trigger.text
        run_id = uuid.UUID(trigger.json()["run_id"])
        process_ingestion_run(run_id)
        assert _run_status(app, run_id) == "succeeded"

        history = client.get(f"/api/v1/pipelines/{pipeline_id}/runs")
        assert history.status_code == 200
        items = history.json()["items"]
        assert len(items) == 1
        assert items[0]["run_id"] == str(run_id)
        assert items[0]["trigger"] == "manual"
        assert items[0]["status"] == "succeeded"
        assert items[0]["records_processed"] == 1000

        # Run detail with batches.
        detail = client.get(f"/api/v1/runs/{run_id}")
        assert detail.status_code == 200
        assert len(detail.json()["batches"]) == 1
        assert detail.json()["batches"][0]["source_object"] == "customer"
        assert detail.json()["batches"][0]["record_count"] == 1000

        # Force a failure on the next run -> retry re-processes only the delta.
        # Remove the table so extract raises -> run fails.
        app.state.source_gateway._sources[source_id].tables.pop("customer")
        fail_trigger = client.post(f"/api/v1/pipelines/{pipeline_id}/run")
        assert fail_trigger.status_code == 202
        fail_run_id = uuid.UUID(fail_trigger.json()["run_id"])
        process_ingestion_run(fail_run_id)
        assert _run_status(app, fail_run_id) == "failed"

        # Restore the table with one new row (newer updated_at) for the retry.
        app.state.source_gateway.add_table(
            source_id,
            SimTable(name="customer", columns=_CUSTOMER_COLUMNS),
            rows=[
                {"customer_id": 1001, "email": "new@example.com", "updated_at": "2026-10-01"},
            ],
        )

        # Retry the failed run.
        retry = client.post(f"/api/v1/runs/{fail_run_id}/retry")
        assert retry.status_code == 202, retry.text
        retry_data = retry.json()
        assert retry_data["trigger"] == "retry"
        assert retry_data["retry_of"] == str(fail_run_id)
        retry_run_id = uuid.UUID(retry_data["run_id"])
        process_ingestion_run(retry_run_id)
        assert _run_status(app, retry_run_id) == "succeeded"

        # Retry re-reads from the uncommitted watermark: only the new row.
        detail2 = client.get(f"/api/v1/runs/{retry_run_id}")
        assert detail2.status_code == 200
        assert detail2.json()["batches"][0]["record_count"] == 1

    def test_pause_skips_schedule_resume_runs(self, app, client, process_ingestion_run):
        pipeline_id, _ = _make_pipeline(app, client)

        # Pause -> schedule elapses with no run started.
        pause = client.post(f"/api/v1/pipelines/{pipeline_id}/pause")
        assert pause.status_code == 200
        assert pause.json()["state"] == "paused"

        from datafoundry.controlplane.ingestion.scheduler import IngestionScheduler

        scheduler = IngestionScheduler(
            app.state.sessionmaker,
            dispatcher=lambda run_id: None,
        )
        scheduler.tick()
        history = client.get(f"/api/v1/pipelines/{pipeline_id}/runs")
        assert history.json()["items"] == []

        # Resume -> runs resume.
        resume = client.post(f"/api/v1/pipelines/{pipeline_id}/resume")
        assert resume.status_code == 200
        assert resume.json()["state"] == "active"

        scheduler.tick()
        history = client.get(f"/api/v1/pipelines/{pipeline_id}/runs")
        items = history.json()["items"]
        assert len(items) == 1
        assert items[0]["trigger"] == "scheduled"
        # Execute the scheduled run to completion.
        process_ingestion_run(uuid.UUID(items[0]["run_id"]))
        assert _run_status(app, uuid.UUID(items[0]["run_id"])) == "succeeded"
