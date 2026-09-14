"""T077: Integration test for quickstart Scenario 7 (health dashboard, US3).

- stop catalog container in dev (mark gateway unhealthy), trigger re-check,
  platform flips to `degraded`, failed component flagged with detail +
  last_check_at.
- capability-disabled platform has no semantic-layer resources (US3-AC1).
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


class TestScenario7HealthDashboard:
    def test_break_component_flips_degraded(self, app, client):
        body = client.post(
            "/api/v1/platforms", json={"config": load_example("dev-aws-localstack.yaml")}
        ).json()
        _process(app, uuid.UUID(body["run_id"]))
        platform_id = body["platform_id"]
        assert client.get(f"/api/v1/platforms/{platform_id}").json()["status"] == "ready"

        # Break the catalog component (stop the container in dev).
        catalog_endpoint = "https://catalog.customer-analytics-dev.datafoundry.internal"
        app.state.gateway.mark_unhealthy(catalog_endpoint)

        # Trigger re-check.
        response = client.post(f"/api/v1/platforms/{platform_id}/health-checks")
        assert response.status_code == 202

        detail = client.get(f"/api/v1/platforms/{platform_id}").json()
        assert detail["status"] == "degraded"
        catalog_health = next(h for h in detail["health"] if h["component"] == "catalog")
        assert catalog_health["status"] == "unhealthy"
        assert catalog_health["detail"]
        assert catalog_health["last_check_at"]

    def test_disabled_capability_no_resources(self, app, client):
        """US3-AC1: semantic_layer disabled -> no semantic-layer resources."""
        body = client.post(
            "/api/v1/platforms", json={"config": load_example("dev-aws-localstack.yaml")}
        ).json()
        _process(app, uuid.UUID(body["run_id"]))
        run_id = uuid.UUID(body["run_id"])
        resources = app.state.gateway.resources_for_run(str(run_id))
        assert not any(r.capability == "semantic_layer" for r in resources)
        assert not any(r.capability == "quality" for r in resources)

        # Recover the component and re-check returns ready (US3-AC3 inverse).
        platform_id = body["platform_id"]
        catalog_endpoint = "https://catalog.customer-analytics-dev.datafoundry.internal"
        app.state.gateway.mark_unhealthy(catalog_endpoint)
        client.post(f"/api/v1/platforms/{platform_id}/health-checks")
        assert client.get(f"/api/v1/platforms/{platform_id}").json()["status"] == "degraded"
        app.state.gateway.mark_healthy(catalog_endpoint)
        client.post(f"/api/v1/platforms/{platform_id}/health-checks")
        assert client.get(f"/api/v1/platforms/{platform_id}").json()["status"] == "ready"
