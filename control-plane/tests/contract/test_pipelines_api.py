"""T038: Contract tests for the pipelines/runs API (ingestion-api.md §3/§4).

Covers:
- GET /pipelines: list with state/schedule/last_run.
- POST /pipelines/{id}/run: 202 {run_id, trigger}; 409 if active run.
- POST /pipelines/{id}/pause / resume: state transitions.
- POST /runs/{id}/retry: 202 {run_id, trigger, retry_of}; 409 if active run.
- GET /pipelines/{id}/runs: history.
- GET /runs/{id}: detail with batches.
- GET /batches/{id}: detail + metadata.
- GET /runs/{id}/logs: log_ref.
"""

from __future__ import annotations

import uuid

PROBLEM_CT = "application/problem+json"


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
    return client.post("/api/v1/sources", json=body).json()["source_id"]


def _valid_config(**overrides):
    config = {
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
    config.update(overrides)
    return config


def _make_pipeline(app, client):
    """Register a source + config, returning the auto-created pipeline_id."""
    source_id = _register_source(app, client)
    response = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["pipeline_id"])


def _queue_run(app, pipeline_id, trigger="manual", status="queued"):
    from datafoundry.controlplane.db.models import IngestionRun, RunTrigger

    with app.state.sessionmaker() as sess:
        run = IngestionRun(
            pipeline_id=pipeline_id,
            trigger=RunTrigger(trigger),
            status=status,
        )
        sess.add(run)
        sess.commit()
        return run.id


class TestListPipelines:
    def test_200_shape(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        response = client.get("/api/v1/pipelines")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["pipeline_id"] == str(pipeline_id)
        assert item["state"] == "active"
        assert item["schedule"] == "every 15 minutes"
        assert item["source"] == "crm-prod"
        assert item["last_run_status"] is None


class TestTriggerRun:
    def test_202_shape(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        response = client.post(f"/api/v1/pipelines/{pipeline_id}/run")
        assert response.status_code == 202, response.text
        data = response.json()
        assert set(data) == {"run_id", "trigger"}
        uuid.UUID(data["run_id"])
        assert data["trigger"] == "manual"

    def test_409_when_active_run(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        _queue_run(app, pipeline_id)
        response = client.post(f"/api/v1/pipelines/{pipeline_id}/run")
        assert response.status_code == 409
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["code"] == "active_run"

    def test_audit_written(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        pipeline_id = _make_pipeline(app, client)
        assert client.post(f"/api/v1/pipelines/{pipeline_id}/run").status_code == 202
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "run.triggered" in actions


class TestPauseResume:
    def test_pause_then_resume(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        pause = client.post(f"/api/v1/pipelines/{pipeline_id}/pause")
        assert pause.status_code == 200
        assert pause.json()["state"] == "paused"
        resume = client.post(f"/api/v1/pipelines/{pipeline_id}/resume")
        assert resume.status_code == 200
        assert resume.json()["state"] == "active"

    def test_audit_written(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        pipeline_id = _make_pipeline(app, client)
        client.post(f"/api/v1/pipelines/{pipeline_id}/pause")
        client.post(f"/api/v1/pipelines/{pipeline_id}/resume")
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "pipeline.paused" in actions
        assert "pipeline.resumed" in actions


class TestRetry:
    def test_202_shape(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        failed_id = _queue_run(app, pipeline_id, status="failed")
        response = client.post(f"/api/v1/runs/{failed_id}/retry")
        assert response.status_code == 202, response.text
        data = response.json()
        assert set(data) == {"run_id", "trigger", "retry_of"}
        assert data["trigger"] == "retry"
        assert data["retry_of"] == str(failed_id)

    def test_409_when_active_run(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        failed_id = _queue_run(app, pipeline_id, status="failed")
        _queue_run(app, pipeline_id)  # second queued run -> active conflict
        response = client.post(f"/api/v1/runs/{failed_id}/retry")
        assert response.status_code == 409
        assert response.json()["code"] == "active_run"

    def test_audit_written(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        pipeline_id = _make_pipeline(app, client)
        failed_id = _queue_run(app, pipeline_id, status="failed")
        assert client.post(f"/api/v1/runs/{failed_id}/retry").status_code == 202
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "run.retried" in actions


class TestRunHistory:
    def test_200_shape(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        run_id = _queue_run(app, pipeline_id)
        response = client.get(f"/api/v1/pipelines/{pipeline_id}/runs")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["run_id"] == str(run_id)
        assert item["trigger"] == "manual"
        assert item["status"] == "queued"
        assert item["records_processed"] == 0


class TestRunDetail:
    def test_200_with_batches(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        run_id = _queue_run(app, pipeline_id)
        from datafoundry.controlplane.db.models import IngestionBatch

        with app.state.sessionmaker() as sess:
            batch = IngestionBatch(
                run_id=run_id,
                pipeline_id=pipeline_id,
                source_object="customer",
                source_system="crm-prod",
                record_count=100,
                status="ingestion_validated",
                metadata_json={"source_object": "customer"},
            )
            sess.add(batch)
            sess.commit()
            batch_id = batch.id

        response = client.get(f"/api/v1/runs/{run_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["run_id"] == str(run_id)
        assert data["pipeline_id"] == str(pipeline_id)
        assert len(data["batches"]) == 1
        assert data["batches"][0]["batch_id"] == str(batch_id)
        assert data["batches"][0]["source_object"] == "customer"
        assert data["batches"][0]["status"] == "ingestion_validated"
        assert data["batches"][0]["record_count"] == 100


class TestBatchDetail:
    def test_200_with_metadata(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        run_id = _queue_run(app, pipeline_id)
        from datafoundry.controlplane.db.models import IngestionBatch

        with app.state.sessionmaker() as sess:
            batch = IngestionBatch(
                run_id=run_id,
                pipeline_id=pipeline_id,
                source_object="customer",
                source_system="crm-prod",
                record_count=100,
                checksum="a" * 64,
                status="ingestion_validated",
                metadata_json={"source_object": "customer", "status": "ingestion_validated"},
            )
            sess.add(batch)
            sess.commit()
            batch_id = batch.id

        response = client.get(f"/api/v1/batches/{batch_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["batch_id"] == str(batch_id)
        assert data["source_system"] == "crm-prod"
        assert data["source_object"] == "customer"
        assert data["record_count"] == 100
        assert data["checksum"] == "a" * 64
        assert data["status"] == "ingestion_validated"
        assert data["metadata"]["source_object"] == "customer"


class TestRunLogs:
    def test_200_log_ref(self, app, client):
        pipeline_id = _make_pipeline(app, client)
        run_id = _queue_run(app, pipeline_id)
        from datafoundry.controlplane.db.models import IngestionRun

        with app.state.sessionmaker() as sess:
            run = sess.get(IngestionRun, run_id)
            run.log_ref = "gs://logs/runs/log.jsonl"
            sess.commit()

        response = client.get(f"/api/v1/runs/{run_id}/logs")
        assert response.status_code == 200, response.text
        assert response.json()["log_ref"] == "gs://logs/runs/log.jsonl"

    def test_404_unknown_run(self, app, client):
        response = client.get(f"/api/v1/runs/{uuid.uuid4()}/logs")
        assert response.status_code == 404
