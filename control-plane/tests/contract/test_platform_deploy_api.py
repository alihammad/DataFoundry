"""T024: Contract tests for POST /api/v1/platforms and POST /api/v1/validate.

Asserts the exact response shapes from contracts/deployment-api.md §1/§3:
- 202 accepted shape {platform_id, run_id, status: "queued"}
- 422 with ALL errors at once, each {path, code, message, remediation}
- 409 name_taken with scope
- 403 insufficient_permissions with missing list
- Idempotency-Key replay returns the original run
- POST /validate: no side effects, same all-errors body
"""

from __future__ import annotations

import uuid

from tests.conftest import load_example

PROBLEM_CT = "application/problem+json"


def _post_platforms(client, config: dict, **kwargs):
    return client.post("/api/v1/platforms", json={"config": config}, **kwargs)


class TestPostPlatformsAccepted:
    def test_202_shape(self, client):
        response = _post_platforms(client, load_example("dev-aws-localstack.yaml"))
        assert response.status_code == 202
        body = response.json()
        assert set(body) == {"platform_id", "run_id", "status"}
        assert body["status"] == "queued"
        uuid.UUID(body["platform_id"])
        uuid.UUID(body["run_id"])

    def test_run_is_queued_with_ordered_steps(self, client):
        response = _post_platforms(client, load_example("dev-aws-localstack.yaml"))
        run_id = response.json()["run_id"]
        run = client.get(f"/api/v1/runs/{run_id}").json()
        keys = [s["key"] for s in run["steps"]]
        # Canonical pre-flight + capability + health steps (R-11).
        assert keys[:4] == [
            "validate-config",
            "generate-tf",
            "validate-tf",
            "permission-check",
        ]
        assert keys[-1] == "health-checks"
        assert "networking" in keys and "storage-zones" in keys
        # Positions are 1-based and strictly ordered.
        positions = [s["position"] for s in run["steps"]]
        assert positions == sorted(positions) and positions[0] == 1

    def test_audit_record_written(self, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        response = _post_platforms(client, load_example("dev-aws-localstack.yaml"))
        assert response.status_code == 202
        with session_factory() as session:
            records = session.query(AuditRecord).all()
        actions = [r.action for r in records]
        assert "deploy.requested" in actions
        record = next(r for r in records if r.action == "deploy.requested")
        assert record.payload["run_id"] == response.json()["run_id"]


class TestPostPlatforms422AllErrors:
    def test_bad_config_returns_all_three_errors_at_once(self, client):
        """quickstart Scenario 1 via API: dependency closure + region + approval."""
        response = _post_platforms(client, load_example("bad-config.yaml"))
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        body = response.json()
        assert body["type"] == "https://datafoundry.example/errors/validation"
        assert body["title"] == "Configuration validation failed"
        assert body["status"] == 422
        codes = {e["code"] for e in body["errors"]}
        assert {"dependency_missing", "region_not_supported", "approval_required"} <= codes
        # Every error carries the full contract shape (SC-007).
        for error in body["errors"]:
            assert set(error) == {"path", "code", "message", "remediation"}
            assert error["remediation"]

    def test_dependency_error_shape_matches_contract_example(self, client):
        response = _post_platforms(client, load_example("bad-config.yaml"))
        errors = response.json()["errors"]
        dep = next(e for e in errors if e["code"] == "dependency_missing")
        assert dep["path"] == "capabilities.semantic_layer"
        assert "catalog" in dep["message"]
        assert "catalog" in dep["remediation"]

    def test_region_error_suggests_supported_regions(self, client):
        response = _post_platforms(client, load_example("bad-config.yaml"))
        region_errors = [
            e for e in response.json()["errors"] if e["code"] == "region_not_supported"
        ]
        assert region_errors and region_errors[0]["path"] == "platform.region"
        assert "us-east-1" in region_errors[0]["remediation"]

    def test_nothing_persisted_on_422(self, client, session_factory):
        from datafoundry.controlplane.db.models import DeploymentRun, Platform

        response = _post_platforms(client, load_example("bad-config.yaml"))
        assert response.status_code == 422
        with session_factory() as session:
            assert session.query(Platform).count() == 0
            assert session.query(DeploymentRun).count() == 0


class TestPostPlatforms409:
    def test_duplicate_name_returns_409_name_taken(self, client):
        config = load_example("dev-aws-localstack.yaml")
        first = _post_platforms(client, config)
        assert first.status_code == 202
        second = _post_platforms(client, config)
        assert second.status_code == 409
        assert second.headers["content-type"].startswith(PROBLEM_CT)
        body = second.json()
        assert body["code"] == "name_taken"
        assert "scope" in body


class TestPostPlatforms403:
    def test_insufficient_permissions_shape(self, client, monkeypatch):
        """When the permission probe reports missing perms -> 403 + list."""
        from datafoundry.controlplane.providers import permissions

        class _Denied:
            unauthenticated = False
            authorised = False
            missing = ("s3:CreateBucket", "kms:CreateKey")
            identity = None
            detail = ""

        monkeypatch.setattr(
            permissions.PermissionChecker, "check", lambda self, adapter, action: _Denied()
        )
        response = _post_platforms(client, load_example("dev-aws-localstack.yaml"))
        assert response.status_code == 403
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        body = response.json()
        assert body["code"] == "insufficient_permissions"
        assert body["missing"] == ["s3:CreateBucket", "kms:CreateKey"]


class TestIdempotencyKey:
    def test_replay_returns_original_run(self, client):
        config = load_example("dev-aws-localstack.yaml")
        headers = {"Idempotency-Key": "unique-key-123"}
        first = _post_platforms(client, config, headers=headers)
        assert first.status_code == 202
        replay = _post_platforms(client, config, headers=headers)
        assert replay.status_code == 202
        assert replay.json() == first.json()

    def test_different_keys_are_independent(self, client):
        config = load_example("dev-aws-localstack.yaml")
        first = _post_platforms(client, config, headers={"Idempotency-Key": "key-a"})
        assert first.status_code == 202
        # Same name without the key -> name_taken conflict, not a replay.
        second = _post_platforms(client, config, headers={"Idempotency-Key": "key-b"})
        assert second.status_code == 409


class TestGetPlatformsList:
    def test_list_shape_and_pagination(self, client):
        config = load_example("dev-aws-localstack.yaml")
        _post_platforms(client, config)
        response = client.get("/api/v1/platforms")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"items", "next_cursor"}
        item = body["items"][0]
        assert set(item) == {
            "id",
            "name",
            "provider",
            "region",
            "environment_type",
            "status",
            "owner",
            "created_at",
        }
        assert item["name"] == config["platform"]["name"]
        assert body["next_cursor"] is None

    def test_cursor_pagination(self, client):
        base = load_example("dev-aws-localstack.yaml")
        for i in range(3):
            config = dict(base)
            config["platform"] = dict(base["platform"], name=f"platform-{i:02d}-abc")
            assert _post_platforms(client, config).status_code == 202
        page = client.get("/api/v1/platforms", params={"limit": 2}).json()
        assert len(page["items"]) == 2
        assert page["next_cursor"]
        rest = client.get(
            "/api/v1/platforms", params={"limit": 2, "cursor": page["next_cursor"]}
        ).json()
        assert len(rest["items"]) == 1
        assert rest["next_cursor"] is None


class TestPostValidate:
    def test_valid_config_returns_200(self, client):
        response = client.post(
            "/api/v1/validate", json={"config": load_example("dev-aws-localstack.yaml")}
        )
        assert response.status_code == 200
        assert response.json() == {"valid": True}

    def test_invalid_config_same_all_errors_body(self, client):
        response = client.post("/api/v1/validate", json={"config": load_example("bad-config.yaml")})
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        codes = {e["code"] for e in response.json()["errors"]}
        assert {"dependency_missing", "region_not_supported", "approval_required"} <= codes

    def test_no_side_effects(self, client, session_factory):
        from datafoundry.controlplane.db.models import DeploymentRun, Platform

        client.post("/api/v1/validate", json={"config": load_example("dev-aws-localstack.yaml")})
        with session_factory() as session:
            assert session.query(Platform).count() == 0
            assert session.query(DeploymentRun).count() == 0

    def test_secret_detected_rejected(self, client):
        config = load_example("dev-aws-localstack.yaml")
        config["secrets"]["refs"]["leaked"] = "AKIAIOSFODNN7EXAMPLE"
        response = client.post("/api/v1/validate", json={"config": config})
        assert response.status_code == 422
        codes = {e["code"] for e in response.json()["errors"]}
        assert "secret_detected" in codes
