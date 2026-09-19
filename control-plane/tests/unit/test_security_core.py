"""T017: Unit tests for security foundational core.

Covers: protection policy schema conformance, classification mapping +
downgrade authorisation, protection mechanism registry, key rotation/revocation,
tokenisation determinism, access chain, and audit hash-chain tamper detection.
"""

from __future__ import annotations

import uuid

import pytest
from datafoundry.controlplane.config.security_schema import (
    SecurityConfigError,
    validate_protection_policy,
)
from datafoundry.controlplane.db.models import (
    AuditResult,
    SecurityLevel,
)
from datafoundry.controlplane.security.classification import is_downgrade, level_rank
from datafoundry.controlplane.security.gateway import SimulatedSecurityGateway
from datafoundry.controlplane.security.protection import (
    ProtectionMechanismError,
    mechanisms,
    protect_value,
)

VALID_POLICY = {
    "name": "restricted-encrypt",
    "classification": "restricted",
    "mechanism": "encrypt",
    "key_ref_id": str(uuid.uuid4()),
    "authorised_roles": ["data-engineer", "security-officer"],
    "detokenise_roles": ["security-officer"],
}


class TestProtectionPolicySchema:
    def test_valid(self):
        model = validate_protection_policy(VALID_POLICY)
        assert model.mechanism == "encrypt"

    def test_unknown_field_rejected(self):
        bad = dict(VALID_POLICY)
        bad["extra"] = "nope"
        with pytest.raises(SecurityConfigError):
            validate_protection_policy(bad)

    def test_invalid_mechanism(self):
        bad = dict(VALID_POLICY)
        bad["mechanism"] = "scramble"
        with pytest.raises(SecurityConfigError):
            validate_protection_policy(bad)

    def test_encrypt_requires_key_ref(self):
        bad = dict(VALID_POLICY)
        bad["key_ref_id"] = None
        with pytest.raises(SecurityConfigError) as exc:
            validate_protection_policy(bad)
        assert any("key_ref_id" in e for e in exc.value.errors)

    def test_tokenise_requires_token_service(self):
        bad = dict(VALID_POLICY)
        bad["mechanism"] = "tokenise"
        bad["token_service_ref"] = None
        with pytest.raises(SecurityConfigError):
            validate_protection_policy(bad)

    def test_detokenise_roles_subset(self):
        bad = dict(VALID_POLICY)
        bad["detokenise_roles"] = ["not-authorized"]
        with pytest.raises(SecurityConfigError):
            validate_protection_policy(bad)

    def test_secret_scan_hit(self):
        bad = dict(VALID_POLICY)
        bad["name"] = "AKIAIOSFODNN7EXAMPLE"
        with pytest.raises(SecurityConfigError):
            validate_protection_policy(bad)


class TestClassification:
    def test_level_rank(self):
        assert level_rank(SecurityLevel.public) < level_rank(SecurityLevel.highly_restricted)

    def test_is_downgrade(self):
        assert is_downgrade(SecurityLevel.restricted, SecurityLevel.internal)
        assert not is_downgrade(SecurityLevel.internal, SecurityLevel.restricted)
        assert not is_downgrade(None, SecurityLevel.restricted)


class TestProtectionMechanisms:
    def test_six_mechanisms(self):
        assert mechanisms() == ["encrypt", "hash", "mask", "pseudonymise", "redact", "tokenise"]

    def test_mask(self):
        gw = SimulatedSecurityGateway()
        result = protect_value(value="a@example.com", mechanism="mask", gateway=gw, policy=None)
        assert result.value == "*" * len("a@example.com")  # no rule -> fully masked
        assert result.status == "protected"

    def test_hash(self):
        gw = SimulatedSecurityGateway()
        result = protect_value(value="secret", mechanism="hash", gateway=gw, policy=None)
        assert result.value != "secret"
        assert len(result.value) == 64

    def test_redact(self):
        gw = SimulatedSecurityGateway()
        result = protect_value(value="secret", mechanism="redact", gateway=gw, policy=None)
        assert result.value == "[REDACTED]"

    def test_encrypt_requires_key(self):
        gw = SimulatedSecurityGateway()
        with pytest.raises(ProtectionMechanismError):
            protect_value(value="x", mechanism="encrypt", gateway=gw, policy=None)

    def test_unknown_mechanism(self):
        gw = SimulatedSecurityGateway()
        with pytest.raises(ProtectionMechanismError):
            protect_value(value="x", mechanism="nope", gateway=gw, policy=None)


class TestKeyLifecycle:
    def test_rotate_keeps_prior_versions(self):
        gw = SimulatedSecurityGateway()
        gw.create_key("key-1", version=1)
        ct = gw.encrypt(key_ref_id="key-1", version=1, value="secret")
        new_version = gw.rotate_key("key-1")
        assert new_version == 2
        # Historical data readable via prior version (FR-009).
        assert gw.decrypt(key_ref_id="key-1", version=1, ciphertext=ct) == "secret"

    def test_revoke_blocks_decryption(self):
        gw = SimulatedSecurityGateway()
        gw.create_key("key-1", version=1)
        ct = gw.encrypt(key_ref_id="key-1", version=1, value="secret")
        gw.revoke_key("key-1")
        with pytest.raises(RuntimeError):
            gw.decrypt(key_ref_id="key-1", version=1, ciphertext=ct)


class TestTokenisation:
    def test_deterministic_same_input_same_token(self):
        gw = SimulatedSecurityGateway()
        t1 = gw.tokenise(value="a@x.com", deterministic=True)
        t2 = gw.tokenise(value="a@x.com", deterministic=True)
        assert t1 == t2

    def test_detokenise_roundtrip(self):
        gw = SimulatedSecurityGateway()
        token = gw.tokenise(value="a@x.com", deterministic=True)
        assert gw.detokenise(token=token) == "a@x.com"


class TestAuditHashChain:
    def test_tamper_detection(self, session_factory):
        from datafoundry.controlplane.security.audit import record_audit, verify_chain

        with session_factory() as sess:
            record_audit(sess, identity="a", action="security.encrypt", result=AuditResult.success)
            record_audit(sess, identity="b", action="security.decrypt", result=AuditResult.success)
            sess.commit()
        with session_factory() as sess:
            assert verify_chain(sess) is True
        # Tamper with the first record's action.
        with session_factory() as sess:
            from datafoundry.controlplane.db.models import SecurityAuditRecord

            first = (
                sess.query(SecurityAuditRecord).order_by(SecurityAuditRecord.occurred_at).first()
            )
            first.action = "security.tokenise"
            sess.commit()
        with session_factory() as sess:
            assert verify_chain(sess) is False
