"""T029: Integration test for quickstart Scenario 3 (US3, FR-011/012).

Tokenise a column, verify deterministic tokens are consistent and joins work,
an unauthorised detokenisation is denied + audited, and an authorised one
succeeds with an audit record.
"""

from __future__ import annotations


def _seed_platform(app):
    from datafoundry.controlplane.db.models import (
        EnvironmentType,
        Platform,
        Provider,
    )

    with app.state.sessionmaker() as sess:
        platform = Platform(
            name="crm-platform",
            provider=Provider.aws,
            cloud_scope_id="scope-1",
            region="us-east-1",
            environment_type=EnvironmentType.test,
            owner_identity="dev@datafoundry.local",
        )
        sess.add(platform)
        sess.commit()
        return platform.id


def _register_dataset(app, client, platform_id, name="customer_silver"):
    body = {
        "platform_id": str(platform_id),
        "name": name,
        "layer": "silver",
        "schema_definition": {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        },
        "owner_identity": "dev@datafoundry.local",
        "classification": "internal",
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _seed_tokenise_policy(app, *, detokenise_roles=None, name="restricted-tokenise"):
    from datafoundry.controlplane.db.models import (
        KeyLifecycleState,
        KeyReference,
        KmsProvider,
        ProtectionMechanism,
        ProtectionPolicy,
        SecurityLevel,
    )

    with app.state.sessionmaker() as sess:
        key = KeyReference(
            kms=KmsProvider.aws_kms,
            key_id="alias/restricted",
            version=1,
            lifecycle_state=KeyLifecycleState.active,
            usage_permissions=["data-engineer"],
        )
        sess.add(key)
        sess.flush()
        policy = ProtectionPolicy(
            name=name,
            classification=SecurityLevel.restricted,
            mechanism=ProtectionMechanism.tokenise,
            key_ref_id=key.id,
            token_service_ref="simulated-token-vault",
            authorised_roles=["data-engineer", "security-officer"],
            detokenise_roles=detokenise_roles or ["security-officer"],
            created_by="dev@datafoundry.local",
        )
        sess.add(policy)
        sess.commit()
        return policy.id


class TestScenario3Tokenisation:
    def test_deterministic_joins_and_audited_detokenise(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_tokenise_policy(app)
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": "email", "policy_id": str(policy_id)},
        )

        # Deterministic: same input -> same token (FR-011).
        body = {"column": "email", "value": "a@x.com", "deterministic": True}
        t1 = client.post(f"/api/v1/datasets/{dataset_id}/tokens/tokenise", json=body).json()[
            "token"
        ]
        t2 = client.post(f"/api/v1/datasets/{dataset_id}/tokens/tokenise", json=body).json()[
            "token"
        ]
        assert t1 == t2

        # Joins work on tokens: same value across two datasets yields the same
        # token, so a join key is consistent.
        dataset2 = _register_dataset(app, client, platform_id, name="customer_gold")
        client.post(
            f"/api/v1/datasets/{dataset2}/classification",
            json={"level": "restricted", "column": "email", "policy_id": str(policy_id)},
        )
        t3 = client.post(f"/api/v1/datasets/{dataset2}/tokens/tokenise", json=body).json()["token"]
        assert t3 == t1  # join on token works

        # Unauthorised detokenisation denied + audited (FR-015).
        denied_policy = _seed_tokenise_policy(
            app, detokenise_roles=["analyst"], name="restricted-tokenise-denied"
        )
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": "email", "policy_id": str(denied_policy)},
        )
        denied = client.post(
            f"/api/v1/datasets/{dataset_id}/tokens/detokenise",
            json={"column": "email", "token": t1, "purpose": "approved-analytics"},
        )
        assert denied.status_code == 403

        # Authorised detokenisation succeeds + audited (FR-012).
        ok_policy = _seed_tokenise_policy(
            app, detokenise_roles=["security-officer"], name="restricted-tokenise-ok"
        )
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": "email", "policy_id": str(ok_policy)},
        )
        ok = client.post(
            f"/api/v1/datasets/{dataset_id}/tokens/detokenise",
            json={"column": "email", "token": t1, "purpose": "approved-analytics"},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["value"] == "a@x.com"

        # Audit trail: denied + success both recorded.
        from datafoundry.controlplane.db.models import SecurityAuditRecord

        with app.state.sessionmaker() as sess:
            denied_records = (
                sess.query(SecurityAuditRecord)
                .filter_by(action="security.detokenise", result="denied")
                .all()
            )
            success_records = (
                sess.query(SecurityAuditRecord)
                .filter_by(action="security.detokenise", result="success")
                .all()
            )
            assert len(denied_records) == 1
            assert any(r.purpose == "approved-analytics" for r in success_records)
