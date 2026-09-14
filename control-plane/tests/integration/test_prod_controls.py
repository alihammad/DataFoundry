"""T068: Integration test for quickstart Scenario 5 (production controls).

- production deploy without approval rejected in validation, nothing provisioned.
- duplicate platform name in same cloud scope -> 409 name_taken, first platform untouched.
"""

from __future__ import annotations

import uuid

from tests.conftest import load_example


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


class TestScenario5ProdControls:
    def test_production_without_approval_rejected_nothing_provisioned(self, app, client):
        response = client.post(
            "/api/v1/platforms", json={"config": load_example("prod-no-approval.yaml")}
        )
        assert response.status_code == 422
        codes = {e["code"] for e in response.json()["errors"]}
        assert "approval_required" in codes
        # Nothing provisioned.
        assert client.get("/api/v1/platforms").json()["items"] == []
        assert app.state.gateway.resources_for_run("any") == []

    def test_duplicate_name_409_first_untouched(self, app, client):
        config = load_example("dev-aws-localstack.yaml")
        first = client.post("/api/v1/platforms", json={"config": config})
        assert first.status_code == 202
        first_body = first.json()
        _process(app, uuid.UUID(first_body["run_id"]))

        second = client.post("/api/v1/platforms", json={"config": config})
        assert second.status_code == 409
        assert second.json()["code"] == "name_taken"

        # First platform untouched: still ready, single platform exists.
        items = client.get("/api/v1/platforms").json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == first_body["platform_id"]
        assert items[0]["status"] == "ready"
