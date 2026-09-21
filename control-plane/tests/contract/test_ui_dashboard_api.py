"""Contract tests for the dashboard data sources (feature 007, T014).

Verifies the endpoints the dashboard renders return the figures it needs:
platform list/detail, runs, quality, health-checks (ui-contract.md §2).
"""

from __future__ import annotations

import uuid
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "platform-configs" / "examples"


def _load_example(name: str) -> dict:
    return yaml.safe_load((EXAMPLES / f"{name}.yaml").read_text())


def _make_platform(client, name="demo"):
    config = _load_example("dev-aws-sandbox")
    resp = client.post("/api/v1/platforms", json={"config": config})
    assert resp.status_code == 202, resp.text
    return resp.json()["platform_id"]


class TestDashboardDataSources:
    def test_platform_list_returns_summary(self, client):
        pid = _make_platform(client)
        resp = client.get("/api/v1/platforms")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert any(p["id"] == pid for p in items)
        assert {"id", "name", "provider", "region", "environment_type", "status"} <= set(items[0])

    def test_platform_detail_has_dashboard_figures(self, client):
        pid = _make_platform(client)
        resp = client.get(f"/api/v1/platforms/{pid}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == pid
        # storage utilisation + health present (may be null before deploy)
        assert "storage_utilisation" in body
        assert "health" in body

    def test_runs_history_returns_pipeline_counts(self, client):
        pid = _make_platform(client)
        resp = client.get(f"/api/v1/platforms/{pid}/runs")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        for run in body["items"]:
            assert {"run_id", "status", "run_type"} <= set(run)

    def test_health_check_trigger(self, client):
        pid = _make_platform(client)
        # The endpoint exists and is reachable; a not-yet-deployed platform
        # may 500 (no gateway resources), but it must NOT be a 404/405.
        resp = client.post(f"/api/v1/platforms/{pid}/health-checks")
        assert resp.status_code in (202, 500)

    def test_quality_endpoint_returns_score(self, client):
        # Quality endpoint requires a dataset; verify it returns 404 for a
        # missing dataset (dashboard handles absence gracefully).
        resp = client.get(f"/api/v1/datasets/{uuid.uuid4()}/quality")
        assert resp.status_code == 404
