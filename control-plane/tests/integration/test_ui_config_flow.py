"""Integration test for quickstart Scenario 2 (feature 007, T020).

Verifies the UI-owned config flow: saved queries, notification channels, and
roles work end to end through the API (US2-AC1/AC2/AC3).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "platform-configs" / "examples"


def _make_platform(client):
    config = yaml.safe_load((EXAMPLES / "dev-aws-sandbox.yaml").read_text())
    resp = client.post("/api/v1/platforms", json={"config": config})
    assert resp.status_code == 202, resp.text
    return resp.json()["platform_id"]


class TestConfigFlow:
    def test_saved_query_lifecycle(self, client):
        # Create (US2-AC1: config created + validated)
        qid = client.post(
            "/api/v1/ui/saved-queries",
            json={
                "name": "revenue",
                "sql_text": "SELECT * FROM gold_orders",
                "dataset_bindings": ["gold_orders"],
            },
        ).json()["query_id"]
        # List + get
        assert any(
            q["query_id"] == qid for q in client.get("/api/v1/ui/saved-queries").json()["items"]
        )
        got = client.get(f"/api/v1/ui/saved-queries/{qid}").json()
        assert got["sql_text"] == "SELECT * FROM gold_orders"
        # Share (US4-AC4)
        share = client.post(
            f"/api/v1/ui/saved-queries/{qid}/share",
            json={"shared_with_identity": "analyst@acme.com"},
        )
        assert share.status_code == 201
        # Run
        run = client.post(f"/api/v1/ui/saved-queries/{qid}/run")
        assert run.status_code == 200
        assert run.json()["sql_text"] == "SELECT * FROM gold_orders"

    def test_notification_channel_lifecycle(self, client):
        pid = _make_platform(client)
        cid = client.post(
            "/api/v1/ui/notifications",
            json={
                "platform_id": pid,
                "channel_type": "email",
                "name": "ops",
                "config": {"recipients": ["ops@example.com"]},
                "event_types": ["gate.failed"],
            },
        ).json()["channel_id"]
        # Update
        upd = client.put(
            f"/api/v1/ui/notifications/{cid}",
            json={"enabled": False},
        )
        assert upd.status_code == 200
        # List never returns config (FR-022)
        items = client.get("/api/v1/ui/notifications").json()["items"]
        assert any(c["channel_id"] == cid and c["enabled"] is False for c in items)
        assert all("config" not in c for c in items)
        # Delete
        assert client.delete(f"/api/v1/ui/notifications/{cid}").status_code == 204

    def test_role_lifecycle(self, client):
        # Create role (US6-AC1)
        rid = client.post(
            "/api/v1/ui/roles",
            json={
                "name": "analyst",
                "scope": "dataset",
                "permissions": ["dataset.read"],
                "dataset_scope": [{"dataset_id": "d1", "columns": ["customer_id"]}],
            },
        ).json()["role_id"]
        # Assign user
        assign = client.post(f"/api/v1/ui/roles/{rid}/assign", json={"user_identity": "u@acme.com"})
        assert assign.status_code == 201
        # List assignments
        assigns = client.get(f"/api/v1/ui/roles/{rid}/assignments").json()["items"]
        assert any(a["user_identity"] == "u@acme.com" for a in assigns)
