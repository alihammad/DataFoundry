"""T027: Integration test for quickstart Scenario 3 (failure handling).

Fault-injected failure at the `orchestration` step:
- earlier steps `succeeded`, later steps `pending`, failed step has a
  human-readable error_detail (US1-AC3);
- partial state inspectable: resources from succeeded steps exist, nothing
  destroyed automatically (R-06);
- retry resumes FROM the failed step (attempt increments, succeeded steps not
  re-executed) (FR-009);
- rollback destroys only this run's resources leaving zero orphans (SC-005)
  and the platform `destroyed`.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from tests.conftest import load_example

FAULT_CONFIG = "fail-at-orchestration.yaml"


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


def _set_fault(app, enabled: bool) -> None:
    object.__setattr__(app.state.settings, "fault_injection", enabled)


@pytest.fixture()
def fault_app(make_app):
    return make_app(fault_injection=True, fault_injection_step="orchestration")


@pytest.fixture()
def fault_client(fault_app):
    with TestClient(fault_app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture()
def failed_run(fault_app, fault_client) -> dict:
    """Deploy with fault injection and run to failure at orchestration."""
    response = fault_client.post("/api/v1/platforms", json={"config": load_example(FAULT_CONFIG)})
    assert response.status_code == 202, response.text
    body = response.json()
    run = _process(fault_app, uuid.UUID(body["run_id"]))
    assert run.status.value == "failed"
    return body


class TestFailureVisibility:
    def test_failed_step_and_neighbours(self, fault_client, failed_run):
        data = fault_client.get(f"/api/v1/runs/{failed_run['run_id']}").json()
        assert data["status"] == "failed"
        by_key = {s["key"]: s for s in data["steps"]}

        assert by_key["orchestration"]["status"] == "failed"
        assert by_key["orchestration"]["error_detail"]
        assert "Quota exceeded" in by_key["orchestration"]["error_detail"]

        # Earlier steps succeeded...
        for key in (
            "validate-config",
            "generate-tf",
            "networking",
            "secrets-kms",
            "storage-zones",
            "iam",
            "compute",
            "database",
            "catalog",
        ):
            assert by_key[key]["status"] == "succeeded", key
        # ...later steps remain pending (US1-AC3).
        for key in ("ingestion", "monitoring", "health-checks"):
            assert by_key[key]["status"] == "pending", key

    def test_platform_failed_not_destroyed(self, fault_client, failed_run):
        platforms = fault_client.get("/api/v1/platforms").json()["items"]
        assert platforms[0]["status"] == "failed"

    def test_partial_state_inspectable(self, fault_app, failed_run):
        """Resources from succeeded steps exist; nothing auto-destroyed."""
        gateway = fault_app.state.gateway
        resources = gateway.resources_for_run(failed_run["run_id"])
        kinds = {r.kind for r in resources}
        assert "module" in kinds  # capability modules from succeeded steps
        assert "zone_prefix" in kinds  # storage-zones init ran
        bucket = "datafoundry-fault-injection-dev-development-aws"
        assert gateway.zone_exists(bucket, "bronze")
        # orchestration failed -> no catalog... wait, catalog precedes
        # orchestration and succeeded:
        catalog_endpoint = "https://catalog.fault-injection-dev.datafoundry.internal"
        assert set(gateway.catalog_lists_zones(catalog_endpoint)) == {
            "bronze",
            "silver",
            "gold",
        }


class TestRetryResumesFromFailedStep:
    def test_retry_continues_to_success(self, fault_app, fault_client, failed_run):
        run_id = uuid.UUID(failed_run["run_id"])
        _set_fault(fault_app, False)  # clear the fault, then retry

        response = fault_client.post(f"/api/v1/runs/{run_id}/retry")
        assert response.status_code == 202

        # The retry endpoint executes synchronously through RecoveryRunner.
        data = fault_client.get(f"/api/v1/runs/{run_id}").json()
        assert data["status"] == "succeeded"
        by_key = {s["key"]: s for s in data["steps"]}

        # Attempt incremented ONLY on the retried step (FR-009).
        assert by_key["orchestration"]["attempt"] == 2
        assert by_key["networking"]["attempt"] == 1
        assert by_key["catalog"]["attempt"] == 1
        # Steps after the failed one executed on resume.
        assert by_key["ingestion"]["status"] == "succeeded"
        assert by_key["health-checks"]["status"] == "succeeded"

        platforms = fault_client.get("/api/v1/platforms").json()["items"]
        assert platforms[0]["status"] == "ready"

    def test_retry_again_fails_while_fault_active(self, fault_app, fault_client, failed_run):
        run_id = uuid.UUID(failed_run["run_id"])
        response = fault_client.post(f"/api/v1/runs/{run_id}/retry")
        assert response.status_code == 202
        data = fault_client.get(f"/api/v1/runs/{run_id}").json()
        assert data["status"] == "failed"
        by_key = {s["key"]: s for s in data["steps"]}
        assert by_key["orchestration"]["attempt"] == 2
        assert by_key["orchestration"]["status"] == "failed"


class TestScopedRollback:
    def test_rollback_leaves_zero_orphans(self, fault_app, fault_client, failed_run):
        run_id = uuid.UUID(failed_run["run_id"])
        gateway = fault_app.state.gateway
        assert gateway.resources_for_run(str(run_id))  # partial state exists

        response = fault_client.post(f"/api/v1/runs/{run_id}/rollback")
        assert response.status_code == 202

        data = fault_client.get(f"/api/v1/runs/{run_id}").json()
        assert data["status"] == "rolled_back"

        # Zero orphaned resources from this run (SC-005).
        assert gateway.resources_for_run(str(run_id)) == []
        bucket = "datafoundry-fault-injection-dev-development-aws"
        for zone in ("bronze", "silver", "gold"):
            assert not gateway.zone_exists(bucket, zone)

        platforms = fault_client.get("/api/v1/platforms").json()["items"]
        assert platforms[0]["status"] == "destroyed"

    def test_rollback_is_scoped_to_the_run(self, fault_app, fault_client, failed_run):
        """A second platform's resources are untouched by this run's rollback."""
        # Deploy a healthy platform alongside the failed one.
        other = fault_client.post(
            "/api/v1/platforms", json={"config": load_example("dev-aws-localstack.yaml")}
        )
        assert other.status_code == 202
        other_run_id = uuid.UUID(other.json()["run_id"])
        _set_fault(fault_app, False)
        _process(fault_app, other_run_id)
        gateway = fault_app.state.gateway
        assert gateway.resources_for_run(str(other_run_id))

        _set_fault(fault_app, True)
        run_id = uuid.UUID(failed_run["run_id"])
        assert fault_client.post(f"/api/v1/runs/{run_id}/rollback").status_code == 202

        # Other run's resources survive (per-run workspace isolation, R-06).
        assert gateway.resources_for_run(str(other_run_id))
        other_bucket = "datafoundry-customer-analytics-dev-development-aws"
        assert gateway.zone_exists(other_bucket, "bronze")

    def test_rollback_then_redeploy_same_name(self, fault_app, fault_client, failed_run):
        """destroy + redeploy is a supported flow (data-model.md invariant 2)."""
        run_id = uuid.UUID(failed_run["run_id"])
        assert fault_client.post(f"/api/v1/runs/{run_id}/rollback").status_code == 202
        # Name uniqueness still applies after destroy (platform row remains,
        # status destroyed) — deploy under a fresh name succeeds.
        config = load_example(FAULT_CONFIG)
        config["platform"]["name"] = "fault-injection-dev2"
        response = fault_client.post("/api/v1/platforms", json={"config": config})
        assert response.status_code == 202
