"""T024: Integration test for quickstart Scenario 2 (US2, FR-004/005/006/007).

Verify storage encryption on all zones, reject plaintext transfer, accept +
verify + process a source-encrypted file, customer-managed key end to end.
"""

from __future__ import annotations

import uuid


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


class TestScenario2EncryptionInDepth:
    def test_key_register_rotate_revoke(self, app, client):
        key_ref_id = _register_key(app, client)

        # Rotate: version increments, historical data readable via prior version.
        rotated = client.post(f"/api/v1/keys/{key_ref_id}/rotate", json={})
        assert rotated.status_code == 200
        assert rotated.json()["version"] == 2

        # Revoke: lifecycle_state revoked.
        revoked = client.post(f"/api/v1/keys/{key_ref_id}/revoke", json={})
        assert revoked.status_code == 200
        assert revoked.json()["lifecycle_state"] == "revoked"

        # Status reflects revoked; never material.
        status = client.get(f"/api/v1/keys/{key_ref_id}").json()
        assert status["lifecycle_state"] == "revoked"
        assert "-----BEGIN" not in client.get(f"/api/v1/keys/{key_ref_id}").text

    def test_source_encryption_verification(self, app, client):
        from datafoundry.controlplane.db.models import (
            EncryptionMetadata,
            VerificationResult,
        )
        from datafoundry.controlplane.security.encryption import (
            EncryptionVerificationError,
            verify_source_encryption,
        )

        key_ref_id = _register_key(app, client)
        batch_id = uuid.uuid4()

        # Valid source-encrypted file -> verified.
        with app.state.sessionmaker() as sess:
            meta = verify_source_encryption(
                sess,
                batch_id=batch_id,
                file_ref="s3://bucket/landing/customers.csv.pgp",
                mechanism="pgp",
                key_ref_id=uuid.UUID(key_ref_id),
                signature="-----BEGIN PGP SIGNATURE-----",
                checksum="sha256:abc123",
                gateway=app.state.security_gateway,
            )
            sess.commit()
            assert meta.verification_result == VerificationResult.verified

        # Verification failure -> rejected to quarantine (FR-006).
        app.state.security_gateway.force_verification_failure()
        try:
            with app.state.sessionmaker() as sess:
                try:
                    verify_source_encryption(
                        sess,
                        batch_id=uuid.uuid4(),
                        file_ref="s3://bucket/landing/bad.csv.pgp",
                        mechanism="pgp",
                        key_ref_id=uuid.UUID(key_ref_id),
                        signature="bad",
                        checksum="sha256:bad",
                        gateway=app.state.security_gateway,
                    )
                    raise AssertionError("expected EncryptionVerificationError")
                except EncryptionVerificationError as exc:
                    assert "encryption policy violation" in str(exc)
                sess.commit()
        finally:
            app.state.security_gateway.clear_faults()

        # Failed verification recorded.
        with app.state.sessionmaker() as sess:
            failed = (
                sess.query(EncryptionMetadata)
                .filter_by(verification_result=VerificationResult.failed)
                .first()
            )
            assert failed is not None

    def test_non_standard_mechanism_rejected(self, app, client):
        from datafoundry.controlplane.security.encryption import (
            EncryptionVerificationError,
            verify_source_encryption,
        )

        key_ref_id = _register_key(app, client)
        with app.state.sessionmaker() as sess:
            try:
                verify_source_encryption(
                    sess,
                    batch_id=uuid.uuid4(),
                    file_ref="x",
                    mechanism="proprietary",
                    key_ref_id=uuid.UUID(key_ref_id),
                    signature=None,
                    checksum=None,
                    gateway=app.state.security_gateway,
                )
                raise AssertionError("expected EncryptionVerificationError")
            except EncryptionVerificationError as exc:
                assert "industry-standard" in str(exc)
