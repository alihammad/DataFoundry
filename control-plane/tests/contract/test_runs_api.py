"""T025: Contract tests for GET /api/v1/runs/{run_id}, POST retry, POST rollback.

Asserts contracts/deployment-api.md §2 shapes:
- ordered steps with per-step status incl. `skipped` + detail
- failed step carries error_detail + attempt
- retry: 202 on failed/paused, 409 otherwise
- rollback: 202 on failed, 409 otherwise
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.conftest import load_example

PROBLEM_CT = "application/problem+json"


def _set_fault(app, enabled: bool) -> None:
    """Toggle fault injection on a frozen Settings (tests only)."""
    object.__setattr__(app.state.settings, "fault_injection", enabled)


def _deploy(client: TestClient, config_name: str = "dev-aws-localstack.yaml") -> dict:
    response = client.post("/api/v1/platforms", json={"config": load_example(config_name)})
    assert response.status_code == 202, response.text
    return response.json()


class TestGetRun:
    def test_queued_run_shape(self, client):
        body = _deploy(client)
        run = client.get(f"/api/v1/runs/{body['run_id']}")
        assert run.status_code == 200
        data = run.json()
        assert set(data) == {"run_id", "platform_id", "status", "steps", "failure"}
        assert data["status"] == "queued"
        assert data["failure"] is None
        assert data["platform_id"] == body["platform_id"]
        for step in data["steps"]:
            assert {"position", "key", "status"} <= set(step)

    def test_unknown_run_404_problem_json(self, client):
        response = client.get(f"/api/v1/runs/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_CT)

    def test_skipped_steps_have_detail(self, client, process_run):
        """Disabled capabilities (quality, semantic_layer) recorded skipped."""
        body = _deploy(client)
        process_run(uuid.UUID(body["run_id"]))
        data = client.get(f"/api/v1/runs/{body['run_id']}").json()
        by_key = {s["key"]: s for s in data["steps"]}
        assert by_key["quality"]["status"] == "skipped"
        assert by_key["quality"]["detail"] == "capability disabled"
        assert by_key["semantic"]["status"] == "skipped"
        assert data["status"] == "succeeded"

    def test_succeeded_run_step_statuses(self, client, process_run):
        body = _deploy(client)
        process_run(uuid.UUID(body["run_id"]))
        data = client.get(f"/api/v1/runs/{body['run_id']}").json()
        statuses = {s["status"] for s in data["steps"]}
        assert statuses <= {"succeeded", "skipped"}
        # Timestamps recorded on executed steps (duration accounting, FR-016).
        executed = [s for s in data["steps"] if s["status"] == "succeeded"]
        assert executed and all(s["started_at"] and s["finished_at"] for s in executed)


class TestFailedRunShape:
    @pytest.fixture()
    def fault_app(self, make_app):
        return make_app(fault_injection=True, fault_injection_step="orchestration")

    @pytest.fixture()
    def fault_client(self, fault_app):
        with TestClient(fault_app, raise_server_exceptions=False) as c:
            yield c

    @pytest.fixture()
    def fault_worker(self, fault_app):
        from datafoundry.controlplane.engine.worker import WorkerRunner

        def _process(run_id):
            session = fault_app.state.sessionmaker()
            try:
                worker = WorkerRunner(
                    session,
                    settings=fault_app.state.settings,
                    gateway=fault_app.state.gateway,
                )
                run = worker.process_run(run_id)
                session.commit()
                return run
            finally:
                session.close()

        return _process

    def test_failed_step_error_detail_and_attempt(self, fault_client, fault_worker):
        body = _deploy(fault_client, "fail-at-orchestration.yaml")
        fault_worker(uuid.UUID(body["run_id"]))
        data = fault_client.get(f"/api/v1/runs/{body['run_id']}").json()
        assert data["status"] == "failed"
        assert data["failure"]
        failed = [s for s in data["steps"] if s["status"] == "failed"]
        assert len(failed) == 1
        assert failed[0]["key"] == "orchestration"
        assert failed[0]["error_detail"]
        assert failed[0]["attempt"] == 1


class TestRunHistory:
    def test_platform_runs_history_shape(self, client, process_run):
        body = _deploy(client)
        process_run(uuid.UUID(body["run_id"]))
        response = client.get(f"/api/v1/platforms/{body['platform_id']}/runs")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        item = data["items"][0]
        assert {
            "run_id",
            "run_type",
            "status",
            "initiated_by",
            "config_version",
            "started_at",
            "finished_at",
            "duration_seconds",
            "outcome",
        } <= set(item)
        assert item["run_type"] == "deploy"
        assert item["status"] == "succeeded"
        assert item["duration_seconds"] is not None

    def test_unknown_platform_404(self, client):
        response = client.get(f"/api/v1/platforms/{uuid.uuid4()}/runs")
        assert response.status_code == 404


class TestRetry:
    def test_retry_409_when_not_failed(self, client):
        body = _deploy(client)
        response = client.post(f"/api/v1/runs/{body['run_id']}/retry")
        assert response.status_code == 409
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["code"] == "run_not_retryable"

    def test_retry_404_unknown_run(self, client):
        response = client.post(f"/api/v1/runs/{uuid.uuid4()}/retry")
        assert response.status_code == 404

    def test_retry_202_and_resumes_from_failed_step(self, make_app):
        app = make_app(fault_injection=True, fault_injection_step="orchestration")
        from datafoundry.controlplane.engine.worker import WorkerRunner

        def _process(run_id):
            session = app.state.sessionmaker()
            try:
                worker = WorkerRunner(
                    session, settings=app.state.settings, gateway=app.state.gateway
                )
                run = worker.process_run(run_id)
                session.commit()
                return run
            finally:
                session.close()

        with TestClient(app, raise_server_exceptions=False) as client:
            body = _deploy(client, "fail-at-orchestration.yaml")
            run_id = uuid.UUID(body["run_id"])
            _process(run_id)
            assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "failed"

            # Clear the fault; retry must succeed and resume from the step.
            _set_fault(app, False)
            response = client.post(f"/api/v1/runs/{run_id}/retry")
            assert response.status_code == 202, response.text
            assert response.json()["run_id"] == str(run_id)

            data = client.get(f"/api/v1/runs/{run_id}").json()
            assert data["status"] == "succeeded"
            by_key = {s["key"]: s for s in data["steps"]}
            # Attempt incremented on the retried step only.
            assert by_key["orchestration"]["attempt"] == 2
            assert by_key["networking"]["attempt"] == 1

    def test_retry_writes_audit(self, make_app, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        app = make_app(fault_injection=True, fault_injection_step="orchestration")
        from datafoundry.controlplane.engine.worker import WorkerRunner

        with TestClient(app, raise_server_exceptions=False) as client:
            body = _deploy(client, "fail-at-orchestration.yaml")
            run_id = uuid.UUID(body["run_id"])
            session = app.state.sessionmaker()
            worker = WorkerRunner(session, settings=app.state.settings, gateway=app.state.gateway)
            worker.process_run(run_id)
            session.commit()
            session.close()
            _set_fault(app, False)
            assert client.post(f"/api/v1/runs/{run_id}/retry").status_code == 202

        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "run.retry" in actions


class TestRollback:
    def test_rollback_409_when_not_failed(self, client, process_run):
        body = _deploy(client)
        process_run(uuid.UUID(body["run_id"]))
        response = client.post(f"/api/v1/runs/{body['run_id']}/rollback")
        assert response.status_code == 409
        assert response.json()["code"] == "run_not_rollbackable"

    def test_rollback_202_and_run_rolled_back(self, make_app):
        app = make_app(fault_injection=True, fault_injection_step="orchestration")
        from datafoundry.controlplane.engine.worker import WorkerRunner

        with TestClient(app, raise_server_exceptions=False) as client:
            body = _deploy(client, "fail-at-orchestration.yaml")
            run_id = uuid.UUID(body["run_id"])
            session = app.state.sessionmaker()
            worker = WorkerRunner(session, settings=app.state.settings, gateway=app.state.gateway)
            worker.process_run(run_id)
            session.commit()
            session.close()

            response = client.post(f"/api/v1/runs/{run_id}/rollback")
            assert response.status_code == 202, response.text
            data = client.get(f"/api/v1/runs/{run_id}").json()
            assert data["status"] == "rolled_back"

            platform = client.get("/api/v1/platforms").json()["items"][0]
            assert platform["status"] == "destroyed"

    def test_rollback_writes_audit(self, make_app, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        app = make_app(fault_injection=True, fault_injection_step="orchestration")
        from datafoundry.controlplane.engine.worker import WorkerRunner

        with TestClient(app, raise_server_exceptions=False) as client:
            body = _deploy(client, "fail-at-orchestration.yaml")
            run_id = uuid.UUID(body["run_id"])
            session = app.state.sessionmaker()
            WorkerRunner(
                session, settings=app.state.settings, gateway=app.state.gateway
            ).process_run(run_id)
            session.commit()
            session.close()
            assert client.post(f"/api/v1/runs/{run_id}/rollback").status_code == 202

        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "rollback.executed" in actions
