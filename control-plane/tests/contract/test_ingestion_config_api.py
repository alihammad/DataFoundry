"""T016: Contract tests for the ingestion config API (ingestion-api.md §2).

Covers:
- POST /sources/{id}/config: 201 {config_id, version, pipeline_id}; 422
  all-errors (invalid schedule, incremental-without-cursor, secret-scan hit).
- GET /sources/{id}/config: version/config_yaml/config_hash; no plaintext
  secrets.
"""

from __future__ import annotations

import uuid

import yaml

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


class TestCreateConfig:
    def test_201_shape(self, app, client):
        source_id = _register_source(app, client)
        response = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"config_id", "version", "pipeline_id"}
        uuid.UUID(data["config_id"])
        uuid.UUID(data["pipeline_id"])
        assert data["version"] == 1

    def test_audit_written(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        source_id = _register_source(app, client)
        response = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        assert response.status_code == 201
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "config.created" in actions

    def test_invalid_schedule_422(self, app, client):
        source_id = _register_source(app, client)
        response = client.post(
            f"/api/v1/sources/{source_id}/config",
            json=_valid_config(schedule="not a schedule"),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_incremental_without_cursor_422(self, app, client):
        source_id = _register_source(app, client)
        config = _valid_config()
        config["source"]["objects"] = [
            {"name": "customer", "mode": "incremental"}  # no cursor_column
        ]
        response = client.post(f"/api/v1/sources/{source_id}/config", json=config)
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_secret_scan_hit_422(self, app, client):
        source_id = _register_source(app, client)
        config = _valid_config()
        config["metadata"]["name"] = "AKIAIOSFODNN7EXAMPLE"
        response = client.post(f"/api/v1/sources/{source_id}/config", json=config)
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert any("secret" in e["message"] for e in response.json()["errors"])

    def test_type_mismatch_422(self, app, client):
        source_id = _register_source(app, client)
        config = _valid_config()
        config["source"]["type"] = "sqlserver"
        response = client.post(f"/api/v1/sources/{source_id}/config", json=config)
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)

    def test_unknown_source_404(self, app, client):
        response = client.post(f"/api/v1/sources/{uuid.uuid4()}/config", json=_valid_config())
        assert response.status_code == 404

    def test_version_increments(self, app, client):
        source_id = _register_source(app, client)
        first = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        assert first.status_code == 201
        second = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        assert second.status_code == 201
        assert second.json()["version"] == 2


class TestExportConfig:
    def test_export_shape(self, app, client):
        source_id = _register_source(app, client)
        client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        response = client.get(f"/api/v1/sources/{source_id}/config")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"version", "config_yaml", "config_hash"}
        assert data["version"] == 1
        assert data["config_hash"].startswith("sha256:")
        assert len(data["config_hash"]) == len("sha256:") + 64
        parsed = yaml.safe_load(data["config_yaml"])
        assert parsed["metadata"]["name"] == "crm-to-bronze"
        assert parsed["source"]["type"] == "postgres"

    def test_export_no_plaintext_secrets(self, app, client):
        source_id = _register_source(app, client)
        client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        data = client.get(f"/api/v1/sources/{source_id}/config").json()
        lowered = data["config_yaml"].lower()
        for marker in ("akia", "asia", "secret_access_key", "private key", "aiza"):
            assert marker not in lowered

    def test_export_unknown_source_404(self, app, client):
        response = client.get(f"/api/v1/sources/{uuid.uuid4()}/config")
        assert response.status_code == 404
