"""T076: Contract tests for platform detail, capabilities, health (US3).

Asserts contracts/deployment-api.md §1/§3/§4 shapes:
- GET /platforms/{id}: health array, storage_utilisation, latest_run,
  recent_failures.
- GET /capabilities: registry catalog incl. providers.
- GET /providers/{provider}/regions?capability=: generated matrix.
- POST /platforms/{id}/health-checks: 202 + check_id.
"""

from __future__ import annotations

import uuid

from tests.conftest import load_example


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


class TestPlatformDetail:
    def test_detail_shape(self, app, client):
        body = _deploy(client)
        _process(app, uuid.UUID(body["run_id"]))
        response = client.get(f"/api/v1/platforms/{body['platform_id']}")
        assert response.status_code == 200
        data = response.json()
        assert {
            "id",
            "name",
            "provider",
            "region",
            "environment_type",
            "status",
            "owner",
            "capabilities_enabled",
            "storage_utilisation",
            "health",
            "latest_run",
            "recent_failures",
        } <= set(data)
        assert data["status"] == "ready"
        assert data["storage_utilisation"] == {
            "bronze_bytes": 0,
            "silver_bytes": 0,
            "gold_bytes": 0,
        } or set(data["storage_utilisation"]) == {
            "bronze_bytes",
            "silver_bytes",
            "gold_bytes",
        }
        # Health array has per-component status + last check time.
        assert data["health"], "expected health results"
        for item in data["health"]:
            assert {"component", "status", "last_check_at", "detail"} <= set(item)
            assert item["status"] == "healthy"
        # Enabled capabilities include implicit database.
        assert "catalog" in data["capabilities_enabled"]
        assert "database" in data["capabilities_enabled"]
        assert data["latest_run"]["status"] == "succeeded"
        assert data["recent_failures"] == []

    def test_detail_unknown_platform_404(self, client):
        assert client.get(f"/api/v1/platforms/{uuid.uuid4()}").status_code == 404


class TestCapabilities:
    def test_capability_catalog_shape(self, client):
        response = client.get("/api/v1/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        items = {c["key"]: c for c in data["items"]}
        catalog = items["catalog"]
        assert catalog["selectable"] is True
        assert catalog["display_name"] == "Metadata Catalog"
        assert "storage_zones" in catalog["depends_on"]
        assert set(catalog["providers"]) == {"aws", "gcp"}
        # Mandatory core is not selectable.
        assert items["networking"]["selectable"] is False


class TestRegionMatrix:
    def test_regions_shape(self, client):
        response = client.get("/api/v1/providers/aws/regions")
        assert response.status_code == 200
        data = response.json()
        assert "regions" in data
        assert data["regions"], "expected regions"
        for region in data["regions"]:
            assert {"id", "capabilities_supported"} <= set(region)
            assert region["id"].startswith(("us-", "ca-", "eu-", "ap-", "sa-"))

    def test_regions_capability_filter(self, client):
        response = client.get("/api/v1/providers/aws/regions", params={"capability": "catalog"})
        assert response.status_code == 200
        regions = response.json()["regions"]
        assert regions
        for region in regions:
            assert region["capabilities_supported"] == ["catalog"]

    def test_regions_unknown_provider_404(self, client):
        response = client.get("/api/v1/providers/azure/regions")
        assert response.status_code == 404


class TestHealthChecks:
    def test_health_checks_202(self, app, client):
        body = _deploy(client)
        _process(app, uuid.UUID(body["run_id"]))
        response = client.post(f"/api/v1/platforms/{body['platform_id']}/health-checks")
        assert response.status_code == 202
        data = response.json()
        assert set(data) == {"check_id"}
        uuid.UUID(data["check_id"])

    def test_health_checks_unknown_platform_404(self, client):
        response = client.post(f"/api/v1/platforms/{uuid.uuid4()}/health-checks")
        assert response.status_code == 404
