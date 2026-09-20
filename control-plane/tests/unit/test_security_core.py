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

    def test_set_classification_records_previous_level_for_lineage(self, session):
        """T044: protection state transitions are traceable (FR-018)."""
        from datafoundry.controlplane.db.models import (
            Classification,
            Dataset,
            EnvironmentType,
            Platform,
            ProtectionPolicy,
            Provider,
            SecurityLevel,
        )
        from datafoundry.controlplane.security.classification import set_classification

        with session.begin():
            platform = Platform(
                name="crm-platform",
                provider=Provider.aws,
                cloud_scope_id="scope-1",
                region="us-east-1",
                environment_type=EnvironmentType.test,
                owner_identity="dev@datafoundry.local",
            )
            session.add(platform)
            session.flush()
            dataset = Dataset(
                platform_id=platform.id,
                name="customer_silver",
                layer="silver",
                schema_definition={"email": {"type": "string"}},
                owner_identity="dev@datafoundry.local",
                classification="internal",
            )
            session.add(dataset)
            session.flush()
            policy = ProtectionPolicy(
                name="restricted-encrypt",
                classification=SecurityLevel.restricted,
                mechanism="encrypt",
                authorised_roles=["data-engineer"],
                created_by="dev@datafoundry.local",
            )
            session.add(policy)
            session.flush()

            set_classification(
                session,
                dataset_id=dataset.id,
                level=SecurityLevel.restricted,
                policy_id=policy.id,
                changed_by="dev@datafoundry.local",
                column="email",
            )
            # Downgrade -> previous_level records the prior restricted state.
            set_classification(
                session,
                dataset_id=dataset.id,
                level=SecurityLevel.internal,
                policy_id=policy.id,
                changed_by="dev@datafoundry.local",
                column="email",
            )
            row = session.query(Classification).filter_by(column="email").one()
            assert row.level == SecurityLevel.internal
            assert row.previous_level == SecurityLevel.restricted


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


class TestFailClosedEnforcement:
    """T045: fail-closed enforcement (FR-019)."""

    def _seed_classified(self, session, *, mechanism="encrypt"):
        from datafoundry.controlplane.db.models import (
            Classification,
            Dataset,
            EnvironmentType,
            Platform,
            ProtectionPolicy,
            Provider,
            SecurityLevel,
        )

        platform = Platform(
            name="crm-platform",
            provider=Provider.aws,
            cloud_scope_id="scope-1",
            region="us-east-1",
            environment_type=EnvironmentType.test,
            owner_identity="dev@datafoundry.local",
        )
        session.add(platform)
        session.flush()
        dataset = Dataset(
            platform_id=platform.id,
            name="customer_silver",
            layer="silver",
            schema_definition={"email": {"type": "string"}},
            owner_identity="dev@datafoundry.local",
            classification="internal",
        )
        session.add(dataset)
        session.flush()
        policy = ProtectionPolicy(
            name="restricted-encrypt",
            classification=SecurityLevel.restricted,
            mechanism=mechanism,
            authorised_roles=["data-engineer"],
            created_by="dev@datafoundry.local",
        )
        session.add(policy)
        session.flush()
        session.add(
            Classification(
                dataset_id=dataset.id,
                column="email",
                level=SecurityLevel.restricted,
                policy_id=policy.id,
                changed_by="dev@datafoundry.local",
            )
        )
        session.flush()
        return dataset.id

    def test_enforceable_when_service_available(self, session):
        from datafoundry.controlplane.security.engine import enforce_protection

        dataset_id = self._seed_classified(session)
        gw = SimulatedSecurityGateway()
        plan = enforce_protection(session, dataset_id=dataset_id, column="email", gateway=gw)
        assert plan.enforceable is True
        assert plan.mechanism == "encrypt"

    def test_fails_closed_when_service_unavailable(self, session):
        from datafoundry.controlplane.security.engine import FailClosedError, enforce_protection

        dataset_id = self._seed_classified(session)
        gw = SimulatedSecurityGateway()
        gw.force_kms_unavailable()
        with pytest.raises(FailClosedError):
            enforce_protection(session, dataset_id=dataset_id, column="email", gateway=gw)

    def test_unclassified_is_enforceable(self, session):
        from datafoundry.controlplane.security.engine import enforce_protection

        gw = SimulatedSecurityGateway()
        plan = enforce_protection(session, dataset_id=uuid.uuid4(), column="email", gateway=gw)
        assert plan.enforceable is True
        assert plan.mechanism == "none"


class TestSecurityAlerts:
    """T046: alerting on security failures (FR-015)."""

    def test_emit_alert_redacts_secrets(self, session):
        from datafoundry.controlplane.security.alerts import emit_security_alert

        emit_security_alert(
            session,
            actor="dev@datafoundry.local",
            kind="failed.detokenise",
            dataset_id=uuid.uuid4(),
            detail={
                "identity": "user@acme.com",
                "column": "email",
                "token": "tok_abc123",
                "value": "AKIAIOSFODNN7EXAMPLE",
            },
        )
        session.flush()
        from datafoundry.controlplane.db.models import AuditRecord

        record = (
            session.query(AuditRecord).filter_by(action="security.alert.failed.detokenise").one()
        )
        payload = record.payload
        assert "token" not in payload
        assert "value" not in payload
        assert payload["identity"] == "user@acme.com"
        assert payload["column"] == "email"
