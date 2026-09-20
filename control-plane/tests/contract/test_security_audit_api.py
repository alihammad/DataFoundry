"""T040: Contract tests for the security audit API (security-api.md §6).

Covers:
- GET /security-audit: search by identity/dataset/action/date range (FR-014).
- GET /security-audit/{id}: full record incl. prev_hash/hash for tamper
  verification (US6-AC1).
"""

from __future__ import annotations

import uuid


def _seed_audit(app, *, identity="user@acme.com", action="security.detokenise", purpose=None):
    """Write a security audit record directly and return its id."""
    from datafoundry.controlplane.db.models import AuditResult
    from datafoundry.controlplane.security.audit import record_audit

    with app.state.sessionmaker() as sess:
        record = record_audit(
            sess,
            identity=identity,
            action=action,
            result=AuditResult.success,
            dataset_id=None,
            column="email",
            purpose=purpose,
            protection_service_ref="simulated-token-vault",
        )
        sess.commit()
        return record.id


class TestListSecurityAudit:
    def test_200_search_by_identity(self, app, client):
        _seed_audit(app, identity="user@acme.com", action="security.tokenise")
        _seed_audit(app, identity="other@acme.com", action="security.detokenise")

        response = client.get("/api/v1/security-audit", params={"identity": "user@acme.com"})
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["identity"] == "user@acme.com"
        assert item["action"] == "security.tokenise"
        assert item["result"] == "success"
        assert item["column"] == "email"
        assert item["protection_service_ref"] == "simulated-token-vault"
        uuid.UUID(item["audit_id"])

    def test_200_search_by_action(self, app, client):
        _seed_audit(app, action="security.tokenise")
        _seed_audit(app, action="security.detokenise", purpose="approved-analytics")

        response = client.get("/api/v1/security-audit", params={"action": "security.detokenise"})
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["action"] == "security.detokenise"
        assert items[0]["purpose"] == "approved-analytics"

    def test_200_empty(self, app, client):
        response = client.get("/api/v1/security-audit")
        assert response.status_code == 200
        assert response.json()["items"] == []


class TestGetSecurityAudit:
    def test_200_full_record_with_hash_chain(self, app, client):
        audit_id = _seed_audit(app, identity="user@acme.com", action="security.detokenise")

        response = client.get(f"/api/v1/security-audit/{audit_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["audit_id"] == str(audit_id)
        assert data["identity"] == "user@acme.com"
        assert data["action"] == "security.detokenise"
        # Tamper-evident hash chain (US6-AC1).
        assert data["hash"]
        assert data["prev_hash"] is None  # first record

    def test_404_unknown(self, app, client):
        response = client.get(f"/api/v1/security-audit/{uuid.uuid4()}")
        assert response.status_code == 404
