"""T026: Integration test for quickstart Scenarios 1+2.

Scenario 1: bad-config rejected with ALL THREE errors and zero resources
created (no platform, no run, empty cloud inventory).

Scenario 2: (simulated) AWS deploy reaches `succeeded`, platform `ready`,
Bronze/Silver/Gold zone prefixes exist, catalog lists the zones, disabled
capabilities recorded `skipped`, audit records written.

Runs against the in-memory SimulatedCloudGateway (no LocalStack/terraform
binary needed); the LocalStack E2E pass is T065/CI.
"""

from __future__ import annotations

import uuid

from tests.conftest import load_example


def _process(app, run_id):
    from datafoundry.controlplane.engine.worker import WorkerRunner

    session = app.state.sessionmaker()
    try:
        run = WorkerRunner(
            session, settings=app.state.settings, gateway=app.state.gateway
        ).process_run(run_id)
        session.commit()
        return run
    finally:
        session.close()


class TestScenario1BadConfigRejected:
    def test_all_three_errors_and_zero_resources(self, app, client):
        response = client.post(
            "/api/v1/platforms", json={"config": load_example("bad-config.yaml")}
        )
        assert response.status_code == 422
        codes = {e["code"] for e in response.json()["errors"]}
        # 1. semantic_layer without catalog, 2. unknown region, 3. no approval.
        assert {"dependency_missing", "region_not_supported", "approval_required"} <= codes

        # Zero resources created: no platform/run rows, empty cloud inventory.
        assert client.get("/api/v1/platforms").json()["items"] == []
        assert app.state.gateway.resources_for_run("any") == []

    def test_validate_endpoint_agrees(self, client):
        response = client.post("/api/v1/validate", json={"config": load_example("bad-config.yaml")})
        assert response.status_code == 422
        assert len(response.json()["errors"]) >= 3

    def test_prod_no_approval_rejected(self, client):
        response = client.post(
            "/api/v1/platforms", json={"config": load_example("prod-no-approval.yaml")}
        )
        assert response.status_code == 422
        codes = {e["code"] for e in response.json()["errors"]}
        assert "approval_required" in codes


class TestScenario2OneClickDeploy:
    def test_deploy_reaches_ready_with_zones_and_catalog(self, app, client):
        response = client.post(
            "/api/v1/platforms", json={"config": load_example("dev-aws-localstack.yaml")}
        )
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "queued"
        run_id = uuid.UUID(body["run_id"])

        run = _process(app, run_id)
        assert run.status.value == "succeeded"
        assert run.started_at and run.finished_at  # wall time recorded (FR-016)

        data = client.get(f"/api/v1/runs/{run_id}").json()
        assert data["status"] == "succeeded"
        by_key = {s["key"]: s for s in data["steps"]}

        # Canonical order (R-11): pre-flight -> capabilities -> health-checks.
        keys = [s["key"] for s in data["steps"]]
        assert keys.index("networking") < keys.index("secrets-kms") < keys.index("storage-zones")
        assert keys.index("storage-zones") < keys.index("catalog")
        assert keys.index("catalog") < keys.index("orchestration")
        assert keys[-1] == "health-checks"

        # Disabled capabilities recorded skipped (FR-012).
        assert by_key["quality"]["status"] == "skipped"
        assert by_key["semantic"]["status"] == "skipped"
        assert by_key["catalog"]["status"] == "succeeded"

        # Platform ready (FR-007).
        platforms = client.get("/api/v1/platforms").json()["items"]
        assert platforms[0]["status"] == "ready"

        # Bronze/Silver/Gold zone prefixes exist (FR-005).
        gateway = app.state.gateway
        bucket = "datafoundry-customer-analytics-dev-development-aws"
        for zone in ("bronze", "silver", "gold"):
            assert gateway.zone_exists(bucket, zone)

        # Catalog lists the zones (FR-005).
        catalog_endpoint = "https://catalog.customer-analytics-dev.datafoundry.internal"
        assert set(gateway.catalog_lists_zones(catalog_endpoint)) == {
            "bronze",
            "silver",
            "gold",
        }

    def test_health_results_persisted_for_enabled_capabilities(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import HealthCheckResult, HealthStatus

        response = client.post(
            "/api/v1/platforms", json={"config": load_example("dev-aws-localstack.yaml")}
        )
        _process(app, uuid.UUID(response.json()["run_id"]))
        with session_factory() as session:
            results = session.query(HealthCheckResult).all()
        components = {r.component for r in results}
        # Enabled capabilities incl. implicit database (auto-enabled via catalog).
        assert {
            "networking",
            "secrets",
            "storage_zones",
            "iam",
            "compute",
            "database",
            "catalog",
            "orchestration",
            "ingestion",
            "monitoring",
        } <= components
        assert all(r.status is HealthStatus.healthy for r in results)
        # Disabled capabilities have NO health results.
        assert "quality" not in components and "semantic_layer" not in components

    def test_deploy_audit_trail(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        response = client.post(
            "/api/v1/platforms", json={"config": load_example("dev-aws-localstack.yaml")}
        )
        _process(app, uuid.UUID(response.json()["run_id"]))
        with session_factory() as session:
            records = session.query(AuditRecord).all()
        assert any(r.action == "deploy.requested" for r in records)
        for record in records:
            assert record.actor and record.occurred_at

    def test_duplicate_deploy_conflicts_after_success(self, app, client):
        config = load_example("dev-aws-localstack.yaml")
        first = client.post("/api/v1/platforms", json={"config": config})
        _process(app, uuid.UUID(first.json()["run_id"]))
        second = client.post("/api/v1/platforms", json={"config": config})
        assert second.status_code == 409
        assert second.json()["code"] == "name_taken"

    def test_gcp_config_deploys_too(self, app, client):
        """Cloud independence (FR-002): the same flow works for GCP configs."""
        response = client.post(
            "/api/v1/platforms", json={"config": load_example("dev-gcp-sandbox.yaml")}
        )
        assert response.status_code == 202, response.text
        run = _process(app, uuid.UUID(response.json()["run_id"]))
        assert run.status.value == "succeeded"
        platforms = client.get("/api/v1/platforms").json()["items"]
        assert platforms[0]["provider"] == "gcp"
        assert platforms[0]["status"] == "ready"


class TestOneActiveRunInvariant:
    def test_second_run_rejected_while_active(self, client):
        """R-12: one active run per platform (queued counts as active)."""
        config = load_example("dev-aws-localstack.yaml")
        first = client.post("/api/v1/platforms", json={"config": config})
        assert first.status_code == 202
        # Same name again -> 409 name_taken (platform exists, run active).
        second = client.post("/api/v1/platforms", json={"config": config})
        assert second.status_code == 409
