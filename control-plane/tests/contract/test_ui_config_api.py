"""Contract tests for the UI-owned config endpoints (feature 007, T019).

Covers saved queries, notification channels, and UI roles per ui-api.md §2-4.
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


class TestSavedQueries:
    def test_create_saved_query(self, client):
        resp = client.post(
            "/api/v1/ui/saved-queries",
            json={
                "name": "revenue",
                "sql_text": "SELECT * FROM gold_orders",
                "dataset_bindings": ["gold_orders"],
            },
        )
        assert resp.status_code == 201, resp.text
        assert "query_id" in resp.json()

    def test_create_saved_query_invalid_sql_secret(self, client):
        resp = client.post(
            "/api/v1/ui/saved-queries",
            json={"name": "leak", "sql_text": "SELECT 'AKIAIOSFODNN7EXAMPLE'"},
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["errors"]

    def test_list_saved_queries(self, client):
        client.post(
            "/api/v1/ui/saved-queries",
            json={"name": "revenue", "sql_text": "SELECT * FROM gold_orders"},
        )
        resp = client.get("/api/v1/ui/saved-queries")
        assert resp.status_code == 200
        assert any(q["name"] == "revenue" for q in resp.json()["items"])

    def test_share_saved_query(self, client):
        qid = client.post(
            "/api/v1/ui/saved-queries",
            json={"name": "revenue", "sql_text": "SELECT * FROM gold_orders"},
        ).json()["query_id"]
        resp = client.post(
            f"/api/v1/ui/saved-queries/{qid}/share",
            json={"shared_with_identity": "analyst@acme.com"},
        )
        assert resp.status_code == 201, resp.text
        assert "share_id" in resp.json()

    def test_share_duplicate_conflict(self, client):
        qid = client.post(
            "/api/v1/ui/saved-queries",
            json={"name": "revenue", "sql_text": "SELECT * FROM gold_orders"},
        ).json()["query_id"]
        client.post(
            f"/api/v1/ui/saved-queries/{qid}/share", json={"shared_with_identity": "a@b.com"}
        )
        resp = client.post(
            f"/api/v1/ui/saved-queries/{qid}/share", json={"shared_with_identity": "a@b.com"}
        )
        assert resp.status_code == 409


class TestNotificationChannels:
    def test_create_channel(self, client):
        pid = _make_platform(client)
        resp = client.post(
            "/api/v1/ui/notifications",
            json={
                "platform_id": pid,
                "channel_type": "email",
                "name": "ops",
                "config": {"recipients": ["ops@example.com"]},
                "event_types": ["gate.failed"],
            },
        )
        assert resp.status_code == 201, resp.text
        assert "channel_id" in resp.json()

    def test_create_channel_secret_scan(self, client):
        pid = _make_platform(client)
        resp = client.post(
            "/api/v1/ui/notifications",
            json={
                "platform_id": pid,
                "channel_type": "webhook",
                "name": "x",
                "config": {"url": "https://x", "token": "AKIAIOSFODNN7EXAMPLE"},
            },
        )
        assert resp.status_code == 422

    def test_list_channels_never_returns_config(self, client):
        pid = _make_platform(client)
        client.post(
            "/api/v1/ui/notifications",
            json={
                "platform_id": pid,
                "channel_type": "email",
                "name": "ops",
                "config": {"recipients": ["ops@example.com"]},
            },
        )
        resp = client.get("/api/v1/ui/notifications")
        assert resp.status_code == 200
        for item in resp.json()["items"]:
            assert "config" not in item


class TestUIRoles:
    def test_create_role(self, client):
        resp = client.post(
            "/api/v1/ui/roles",
            json={"name": "analyst", "scope": "dataset", "permissions": ["dataset.read"]},
        )
        assert resp.status_code == 201, resp.text
        assert "role_id" in resp.json()

    def test_create_role_invalid_scope(self, client):
        resp = client.post(
            "/api/v1/ui/roles",
            json={"name": "x", "scope": "bogus", "permissions": []},
        )
        assert resp.status_code == 422

    def test_assign_role(self, client):
        rid = client.post(
            "/api/v1/ui/roles",
            json={"name": "analyst", "scope": "dataset", "permissions": ["dataset.read"]},
        ).json()["role_id"]
        resp = client.post(f"/api/v1/ui/roles/{rid}/assign", json={"user_identity": "u@acme.com"})
        assert resp.status_code == 201, resp.text
        assert "assignment_id" in resp.json()

    def test_assign_duplicate_conflict(self, client):
        rid = client.post(
            "/api/v1/ui/roles",
            json={"name": "analyst", "scope": "dataset", "permissions": []},
        ).json()["role_id"]
        client.post(f"/api/v1/ui/roles/{rid}/assign", json={"user_identity": "u@acme.com"})
        resp = client.post(f"/api/v1/ui/roles/{rid}/assign", json={"user_identity": "u@acme.com"})
        assert resp.status_code == 409
