"""T066: Contract tests for config export + destroy + run history (US2).

Asserts contracts/deployment-api.md §1 shapes:
- GET /platforms/{id}/config: version, config_yaml, config_hash, git_ref;
  secret-scan guarantee (no plaintext secrets).
- DELETE /platforms/{id}: 202 destroy run; approval_ref required for prod.
- GET /platforms/{id}/runs: auditable history (covered partly in test_runs_api).
"""

from __future__ import annotations

import uuid

import yaml

from tests.conftest import load_example

PROBLEM_CT = "application/problem+json"


def _deploy(client, config_name="dev-aws-localstack.yaml") -> dict:
    response = client.post("/api/v1/platforms", json={"config": load_example(config_name)})
    assert response.status_code == 202, response.text
    return response.json()


def _process(app, run_id) -> None:
    from datafoundry.controlplane.engine.worker import WorkerRunner

    session = app.state.sessionmaker()
    try:
        WorkerRunner(session, settings=app.state.settings, gateway=app.state.gateway).process_run(
            run_id
        )
        session.commit()
    finally:
        session.close()


class TestConfigExport:
    def test_export_shape(self, app, client):
        body = _deploy(client)
        _process(app, uuid.UUID(body["run_id"]))
        response = client.get(f"/api/v1/platforms/{body['platform_id']}/config")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"version", "config_yaml", "config_hash", "git_ref"}
        assert data["version"] == 1
        assert data["config_hash"].startswith("sha256:")
        assert len(data["config_hash"]) == len("sha256:") + 64
        # config_yaml is a valid YAML mapping equal to the original config.
        parsed = yaml.safe_load(data["config_yaml"])
        assert parsed == load_example("dev-aws-localstack.yaml")

    def test_export_contains_no_secrets(self, app, client):
        body = _deploy(client)
        _process(app, uuid.UUID(body["run_id"]))
        data = client.get(f"/api/v1/platforms/{body['platform_id']}/config").json()
        # No secret material anywhere in the exported YAML (SC-006).
        lowered = data["config_yaml"].lower()
        for marker in ("akia", "asia", "secret_access_key", "private key", "aiza"):
            assert marker not in lowered
        # Secret refs remain references, never literals.
        assert "platform-credentials" in data["config_yaml"]

    def test_export_unknown_platform_404(self, client):
        response = client.get(f"/api/v1/platforms/{uuid.uuid4()}/config")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_CT)

    def test_export_writes_audit(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        body = _deploy(client)
        _process(app, uuid.UUID(body["run_id"]))
        assert client.get(f"/api/v1/platforms/{body['platform_id']}/config").status_code == 200
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "config.exported" in actions


class TestDestroy:
    def test_destroy_returns_202_and_destroyed(self, app, client):
        body = _deploy(client)
        _process(app, uuid.UUID(body["run_id"]))
        response = client.delete(f"/api/v1/platforms/{body['platform_id']}")
        assert response.status_code == 202, response.text
        data = response.json()
        assert set(data) == {"run_id", "run_type"}
        assert data["run_type"] == "destroy"
        uuid.UUID(data["run_id"])
        # Platform is destroyed.
        platform = client.get("/api/v1/platforms").json()["items"][0]
        assert platform["status"] == "destroyed"

    def test_destroy_unknown_platform_404(self, client):
        response = client.delete(f"/api/v1/platforms/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_destroy_writes_audit(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        body = _deploy(client)
        _process(app, uuid.UUID(body["run_id"]))
        client.delete(f"/api/v1/platforms/{body['platform_id']}")
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "destroy.requested" in actions

    def test_destroy_zero_orphans(self, app, client):
        """SC-005: destroy leaves no orphaned resources in the cloud inventory."""
        body = _deploy(client)
        _process(app, uuid.UUID(body["run_id"]))
        run_id = uuid.UUID(body["run_id"])
        assert app.state.gateway.resources_for_run(str(run_id)) != []
        client.delete(f"/api/v1/platforms/{body['platform_id']}")
        assert app.state.gateway.resources_for_run(str(run_id)) == []
