"""Contract tests for the admin endpoints (feature 007, T041).

Covers roles, approvals, and audit-log search per ui-api.md §4-6.
"""

from __future__ import annotations


class TestAdminRoles:
    def test_create_role(self, client):
        resp = client.post(
            "/api/v1/ui/roles",
            json={"name": "analyst", "scope": "dataset", "permissions": ["dataset.read"]},
        )
        assert resp.status_code == 201, resp.text
        assert "role_id" in resp.json()

    def test_assign_role(self, client):
        rid = client.post(
            "/api/v1/ui/roles",
            json={"name": "analyst", "scope": "dataset", "permissions": []},
        ).json()["role_id"]
        resp = client.post(f"/api/v1/ui/roles/{rid}/assign", json={"user_identity": "u@acme.com"})
        assert resp.status_code == 201, resp.text

    def test_assign_duplicate_conflict(self, client):
        rid = client.post(
            "/api/v1/ui/roles",
            json={"name": "analyst", "scope": "dataset", "permissions": []},
        ).json()["role_id"]
        client.post(f"/api/v1/ui/roles/{rid}/assign", json={"user_identity": "u@acme.com"})
        resp = client.post(f"/api/v1/ui/roles/{rid}/assign", json={"user_identity": "u@acme.com"})
        assert resp.status_code == 409


class TestAdminApprovals:
    def test_list_approvals(self, client):
        resp = client.get("/api/v1/ui/approvals")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_decide_missing_approval_404(self, client):
        import uuid

        resp = client.post(
            f"/api/v1/ui/approvals/{uuid.uuid4()}/decide",
            json={"decision": "approved", "reasoning": "ok"},
        )
        assert resp.status_code == 404

    def test_decide_missing_reasoning_422(self, client):
        import uuid

        resp = client.post(
            f"/api/v1/ui/approvals/{uuid.uuid4()}/decide",
            json={"decision": "approved", "reasoning": ""},
        )
        assert resp.status_code == 422


class TestAdminAuditLog:
    def test_search_audit_log(self, client):
        resp = client.get("/api/v1/ui/audit-log")
        assert resp.status_code == 200
        assert "items" in resp.json()

    def test_search_audit_log_by_action(self, client):
        resp = client.get("/api/v1/ui/audit-log", params={"action": "deploy.requested"})
        assert resp.status_code == 200
        assert "items" in resp.json()
