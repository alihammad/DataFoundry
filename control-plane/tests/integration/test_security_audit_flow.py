"""T041: Integration test for quickstart Scenario 6 (US6, FR-014/015).

Perform a scripted set of security-sensitive operations, verify each appears
in the audit log with complete fields, and verify tampering is detectable.
"""

from __future__ import annotations


def _seed_audit(app, *, identity="user@acme.com", action="security.detokenise", purpose=None):
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


class TestScenario6SecurityAudit:
    def test_scripted_operations_appear_with_complete_fields(self, app, client):
        # Scripted security-sensitive operations.
        _seed_audit(app, identity="user@acme.com", action="security.tokenise")
        _seed_audit(
            app,
            identity="user@acme.com",
            action="security.detokenise",
            purpose="approved-analytics",
        )
        _seed_audit(app, identity="other@acme.com", action="security.key_rotate")

        # Search by identity returns complete fields (FR-014).
        response = client.get("/api/v1/security-audit", params={"identity": "user@acme.com"})
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 2
        for item in items:
            assert item["identity"] == "user@acme.com"
            assert item["occurred_at"]
            assert item["action"]
            assert item["result"] == "success"
            assert item["column"] == "email"
            assert item["protection_service_ref"] == "simulated-token-vault"

        # Search by action.
        detokenise = client.get(
            "/api/v1/security-audit", params={"action": "security.detokenise"}
        ).json()["items"]
        assert len(detokenise) == 1
        assert detokenise[0]["purpose"] == "approved-analytics"

    def test_tampering_detectable(self, app, client):
        from datafoundry.controlplane.security.audit import verify_chain

        audit_id = _seed_audit(app, identity="user@acme.com", action="security.tokenise")
        _seed_audit(app, identity="user@acme.com", action="security.detokenise")

        # Chain verifies before tampering.
        with app.state.sessionmaker() as sess:
            assert verify_chain(sess) is True

        # Tamper with a record -> chain breaks (US6-AC1).
        with app.state.sessionmaker() as sess:
            from datafoundry.controlplane.db.models import SecurityAuditRecord

            record = sess.get(SecurityAuditRecord, audit_id)
            record.identity = "attacker@acme.com"
            sess.commit()

        with app.state.sessionmaker() as sess:
            assert verify_chain(sess) is False

        # The tampered record's hash no longer matches its recomputed hash.
        detail = client.get(f"/api/v1/security-audit/{audit_id}").json()
        assert detail["identity"] == "attacker@acme.com"
        assert detail["hash"]  # stored hash is stale vs recomputed chain
