"""T023: Contract tests for the keys API (security-api.md §3).

Covers:
- POST /keys: 201 key_ref_id/version; 422 invalid kms / missing key_id /
  secret-scan hit.
- POST /keys/{id}/rotate: 200 version++.
- POST /keys/{id}/revoke: 200 revoked.
- GET /keys/{id}: status, never material.
"""

from __future__ import annotations

import uuid

PROBLEM_CT = "application/problem+json"


def _valid_key(**overrides):
    body = {
        "kms": "aws_kms",
        "key_id": "alias/restricted",
        "version": 1,
        "rotation_schedule": "90d",
        "usage_permissions": ["data-engineer"],
    }
    body.update(overrides)
    return body


class TestRegisterKey:
    def test_201_shape(self, app, client):
        response = client.post("/api/v1/keys", json=_valid_key())
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"key_ref_id", "version"}
        uuid.UUID(data["key_ref_id"])
        assert data["version"] == 1

    def test_422_invalid_kms(self, app, client):
        response = client.post("/api/v1/keys", json=_valid_key(kms="vault"))
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_422_missing_key_id(self, app, client):
        response = client.post("/api/v1/keys", json=_valid_key(key_id=""))
        assert response.status_code == 422
        assert response.json()["errors"]

    def test_422_secret_scan_hit(self, app, client):
        response = client.post("/api/v1/keys", json=_valid_key(key_id="AKIAIOSFODNN7EXAMPLE"))
        assert response.status_code == 422
        assert response.json()["errors"]


class TestRotateKey:
    def test_200_version_increments(self, app, client):
        key_ref_id = client.post("/api/v1/keys", json=_valid_key()).json()["key_ref_id"]
        response = client.post(f"/api/v1/keys/{key_ref_id}/rotate", json={})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["version"] == 2
        assert data["lifecycle_state"] == "active"

    def test_404_unknown(self, app, client):
        response = client.post(f"/api/v1/keys/{uuid.uuid4()}/rotate", json={})
        assert response.status_code == 404


class TestRevokeKey:
    def test_200_revoked(self, app, client):
        key_ref_id = client.post("/api/v1/keys", json=_valid_key()).json()["key_ref_id"]
        response = client.post(f"/api/v1/keys/{key_ref_id}/revoke", json={})
        assert response.status_code == 200, response.text
        assert response.json()["lifecycle_state"] == "revoked"


class TestKeyStatus:
    def test_200_never_material(self, app, client):
        key_ref_id = client.post("/api/v1/keys", json=_valid_key()).json()["key_ref_id"]
        response = client.get(f"/api/v1/keys/{key_ref_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["key_ref_id"] == key_ref_id
        assert data["kms"] == "aws_kms"
        assert data["key_id"] == "alias/restricted"
        assert data["version"] == 1
        assert data["lifecycle_state"] == "active"
        # Never material: no key bytes in the response.
        assert "-----BEGIN" not in response.text

    def test_404_unknown(self, app, client):
        response = client.get(f"/api/v1/keys/{uuid.uuid4()}")
        assert response.status_code == 404


class TestKeyLifecycle:
    """T032: Key rotation/revocation lifecycle (US4, FR-008/009, SC-003)."""

    def test_rotate_keeps_historical_readable_new_writes_use_current(self, app, client):
        key_ref_id = client.post("/api/v1/keys", json=_valid_key()).json()["key_ref_id"]
        gateway = app.state.security_gateway

        # Encrypt with version 1 (historical data).
        historical = gateway.encrypt(key_ref_id=key_ref_id, version=1, value="secret-a")

        # Rotate -> version 2 (FR-009).
        rotated = client.post(f"/api/v1/keys/{key_ref_id}/rotate", json={})
        assert rotated.status_code == 200
        assert rotated.json()["version"] == 2

        # Historical data remains readable via prior version (FR-009).
        assert (
            gateway.decrypt(key_ref_id=key_ref_id, version=1, ciphertext=historical) == "secret-a"
        )

        # New writes use the current version (2).
        assert gateway.key_version(key_ref_id) == 2
        current = gateway.encrypt(key_ref_id=key_ref_id, version=2, value="secret-b")
        assert gateway.decrypt(key_ref_id=key_ref_id, version=2, ciphertext=current) == "secret-b"

    def test_revoke_blocks_decryption_and_audited(self, app, client):
        key_ref_id = client.post("/api/v1/keys", json=_valid_key()).json()["key_ref_id"]
        gateway = app.state.security_gateway
        ciphertext = gateway.encrypt(key_ref_id=key_ref_id, version=1, value="secret-a")

        revoked = client.post(f"/api/v1/keys/{key_ref_id}/revoke", json={})
        assert revoked.status_code == 200
        assert revoked.json()["lifecycle_state"] == "revoked"

        # Further decryption with the revoked version fails (FR-008).
        try:
            gateway.decrypt(key_ref_id=key_ref_id, version=1, ciphertext=ciphertext)
            raise AssertionError("expected revoked-key failure")
        except RuntimeError as exc:
            assert "revoked" in str(exc)

        # Revocation audited (FR-008).
        with app.state.sessionmaker() as sess:
            from datafoundry.controlplane.db.models import AuditRecord

            records = sess.query(AuditRecord).filter_by(action="security.key_revoke").all()
            assert len(records) == 1

    def test_no_key_material_in_any_response(self, app, client):
        key_ref_id = client.post("/api/v1/keys", json=_valid_key()).json()["key_ref_id"]
        for path in (
            f"/api/v1/keys/{key_ref_id}",
            f"/api/v1/keys/{key_ref_id}/rotate",
            f"/api/v1/keys/{key_ref_id}/revoke",
        ):
            method = (
                client.get
                if path.endswith(key_ref_id) and "rotate" not in path and "revoke" not in path
                else client.post
            )
            response = method(path, json={}) if method is client.post else method(path)
            assert "-----BEGIN" not in response.text
            assert "AKIA" not in response.text
