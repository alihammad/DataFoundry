"""T047: Security hardening pass for ingestion (SC-007, FR-016).

Verifies zero plaintext credentials across ingestion write/export paths and
API responses:
- source registration rejects a literal credential value (secret-scan).
- source detail + config export carry no secret material.
- run/batch/error payloads are redacted of secret patterns.
- pipelines/runs API responses leak no secret material.
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


def _register_source(app, client, **overrides):
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
    body.update(overrides)
    return client.post("/api/v1/sources", json=body)


def _valid_config():
    return {
        "apiVersion": "datafoundry/v1",
        "kind": "IngestionConfig",
        "metadata": {"name": "crm-to-bronze", "source": "crm-prod"},
        "source": {
            "type": "postgres",
            "objects": [
                {"name": "customer", "mode": "incremental", "cursor_column": "updated_at"},
            ],
        },
        "schedule": "every 15 minutes",
        "target": {"zone": "bronze"},
        "validation": {"reconciliation_tolerance": 0, "contract_mode": "enforce"},
    }


class TestSourceRegistrationSecretScan:
    def test_literal_credential_rejected_422(self, app, client):
        response = _register_source(
            app,
            client,
            config={
                "host": "crm.internal",
                "port": 5432,
                "database": "crm",
                "credentials": {"secretRef": "AKIAIOSFODNN7EXAMPLE"},
            },
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_secret_ref_name_only_in_detail(self, app, client):
        response = _register_source(app, client)
        assert response.status_code == 201, response.text
        source_id = response.json()["source_id"]
        detail = client.get(f"/api/v1/sources/{source_id}")
        assert detail.status_code == 200
        # secretRef name present, never a value; no secret material anywhere.
        assert detail.json()["config"]["credentials"]["secretRef"] == "crm-ro-user"
        assert "AKIA" not in detail.text
        assert "password" not in detail.text.lower()


class TestConfigExportNoSecrets:
    def test_export_has_no_plaintext(self, app, client):
        source_id = _register_source(app, client).json()["source_id"]
        assert (
            client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config()).status_code
            == 201
        )
        exported = client.get(f"/api/v1/sources/{source_id}/config")
        assert exported.status_code == 200
        assert "AKIA" not in exported.text
        assert "password" not in exported.text.lower()


class TestRunBatchPayloadsRedacted:
    def test_run_history_and_detail_no_secrets(self, app, client, process_ingestion_run):
        from datafoundry.controlplane.ingestion.gateway import SimTable

        source_id = _register_source(app, client).json()["source_id"]
        app.state.source_gateway.seed_database(
            str(source_id),
            source_type="postgres",
            tables={
                "customer": SimTable(
                    name="customer",
                    columns=[
                        {"name": "customer_id", "type": "integer", "nullable": False},
                        {"name": "email", "type": "string", "nullable": False},
                    ],
                )
            },
        )
        app.state.source_gateway.add_table(
            str(source_id),
            SimTable(
                name="customer",
                columns=[
                    {"name": "customer_id", "type": "integer", "nullable": False},
                    {"name": "email", "type": "string", "nullable": False},
                ],
            ),
            rows=[{"customer_id": 1, "email": "a@b.com"}],
        )
        config = client.post(f"/api/v1/sources/{source_id}/config", json=_valid_config())
        pipeline_id = uuid.UUID(config.json()["pipeline_id"])
        trigger = client.post(f"/api/v1/pipelines/{pipeline_id}/run")
        run_id = uuid.UUID(trigger.json()["run_id"])
        process_ingestion_run(run_id)

        history = client.get(f"/api/v1/pipelines/{pipeline_id}/runs")
        detail = client.get(f"/api/v1/runs/{run_id}")
        for response in (history, detail):
            assert response.status_code == 200
            assert "AKIA" not in response.text
            assert "password" not in response.text.lower()
            assert "secret" not in response.text.lower()
