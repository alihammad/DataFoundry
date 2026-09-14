"""T067: Integration test for quickstart Scenario 4 (reproducibility, US2).

Export -> destroy -> redeploy produces a matching platform (diff only
timestamps/run ids), identical config_hash (determinism), gitleaks-clean
export (no secrets).
"""

from __future__ import annotations

import uuid

import yaml

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


class TestScenario4Reproducibility:
    def test_export_destroy_redeploy_matches(self, app, client):
        # Deploy.
        first = client.post(
            "/api/v1/platforms", json={"config": load_example("dev-aws-localstack.yaml")}
        )
        assert first.status_code == 202
        first_body = first.json()
        _process(app, uuid.UUID(first_body["run_id"]))
        assert (
            client.get(f"/api/v1/platforms/{first_body['platform_id']}").json()["status"] == "ready"
        )

        # Export.
        export = client.get(f"/api/v1/platforms/{first_body['platform_id']}/config")
        assert export.status_code == 200
        exported = export.json()
        original_hash = exported["config_hash"]

        # Destroy.
        destroy = client.delete(f"/api/v1/platforms/{first_body['platform_id']}")
        assert destroy.status_code == 202
        assert client.get("/api/v1/platforms").json()["items"][0]["status"] == "destroyed"

        # Redeploy from the exported config (must be a clean YAML doc).
        redeploy_config = yaml.safe_load(exported["config_yaml"])
        second = client.post("/api/v1/platforms", json={"config": redeploy_config})
        assert second.status_code == 202, second.text
        second_body = second.json()
        _process(app, uuid.UUID(second_body["run_id"]))

        detail = client.get(f"/api/v1/platforms/{second_body['platform_id']}").json()
        assert detail["status"] == "ready"
        # Same capabilities / zones / settings (only ids/timestamps differ).
        assert detail["name"] == "customer-analytics-dev"
        assert detail["provider"] == "aws"
        assert detail["region"] == "us-east-1"
        assert "catalog" in detail["capabilities_enabled"]
        assert "semantic_layer" not in detail["capabilities_enabled"]

        # config_hash determinism: export hash == redeployed version hash.
        re_export = client.get(f"/api/v1/platforms/{second_body['platform_id']}/config").json()
        assert re_export["config_hash"] == original_hash

    def test_export_is_gitleaks_clean(self, app, client):
        """SC-006: exported YAML contains no detectable secret material."""
        body = client.post(
            "/api/v1/platforms", json={"config": load_example("dev-aws-localstack.yaml")}
        ).json()
        _process(app, uuid.UUID(body["run_id"]))
        exported = client.get(f"/api/v1/platforms/{body['platform_id']}/config").json()[
            "config_yaml"
        ]

        from datafoundry.controlplane.config.secret_scan import scan_yaml_text

        assert scan_yaml_text(exported) == [], "exported config leaks secret material"
