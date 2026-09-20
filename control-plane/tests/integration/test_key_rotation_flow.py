"""T033: Integration test for quickstart Scenario 4 (US4, FR-008/009).

Rotate a key, verify old versions decrypt historical data while new writes use
the new version; revoke a key, verify decryption fails + audited; verify no key
material in exports.
"""

from __future__ import annotations


def _register_key(app, client):
    response = client.post(
        "/api/v1/keys",
        json={
            "kms": "aws_kms",
            "key_id": "alias/restricted",
            "version": 1,
            "rotation_schedule": "90d",
            "usage_permissions": ["data-engineer"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["key_ref_id"]


class TestScenario4KeyRotation:
    def test_rotation_keeps_historical_readable(self, app, client):
        key_ref_id = _register_key(app, client)
        gateway = app.state.security_gateway

        # Historical data encrypted under version 1.
        historical = gateway.encrypt(key_ref_id=key_ref_id, version=1, value="secret-a")

        # Rotate -> version 2 (FR-009).
        rotated = client.post(f"/api/v1/keys/{key_ref_id}/rotate", json={})
        assert rotated.status_code == 200
        assert rotated.json()["version"] == 2

        # Old version still decrypts historical data (FR-009).
        assert (
            gateway.decrypt(key_ref_id=key_ref_id, version=1, ciphertext=historical) == "secret-a"
        )

        # New writes use the current version (2).
        assert gateway.key_version(key_ref_id) == 2
        current = gateway.encrypt(key_ref_id=key_ref_id, version=2, value="secret-b")
        assert gateway.decrypt(key_ref_id=key_ref_id, version=2, ciphertext=current) == "secret-b"

    def test_revoke_blocks_decryption_and_audited(self, app, client):
        key_ref_id = _register_key(app, client)
        gateway = app.state.security_gateway
        ciphertext = gateway.encrypt(key_ref_id=key_ref_id, version=1, value="secret-a")

        revoked = client.post(f"/api/v1/keys/{key_ref_id}/revoke", json={})
        assert revoked.status_code == 200
        assert revoked.json()["lifecycle_state"] == "revoked"

        # Decryption with the revoked version fails (FR-008).
        try:
            gateway.decrypt(key_ref_id=key_ref_id, version=1, ciphertext=ciphertext)
            raise AssertionError("expected revoked-key failure")
        except RuntimeError as exc:
            assert "revoked" in str(exc)

        # Revocation audited (FR-008).
        from datafoundry.controlplane.db.models import AuditRecord

        with app.state.sessionmaker() as sess:
            records = sess.query(AuditRecord).filter_by(action="security.key_revoke").all()
            assert len(records) == 1

    def test_no_key_material_in_exports(self, app, client):
        key_ref_id = _register_key(app, client)
        # Status + rotate + revoke responses never expose material (SC-003).
        status = client.get(f"/api/v1/keys/{key_ref_id}")
        assert "-----BEGIN" not in status.text
        assert "AKIA" not in status.text
        rotated = client.post(f"/api/v1/keys/{key_ref_id}/rotate", json={})
        assert "-----BEGIN" not in rotated.text
        revoked = client.post(f"/api/v1/keys/{key_ref_id}/revoke", json={})
        assert "-----BEGIN" not in revoked.text
