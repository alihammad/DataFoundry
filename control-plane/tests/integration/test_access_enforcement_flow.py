"""T037: Integration test for quickstart Scenario 5 (US5, FR-013).

Users of different roles query the same dataset; verify column protections
differ by role and key-use permission is separately enforced from data-read.
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


def _register_dataset(app, client, platform_id):
    body = {
        "platform_id": str(platform_id),
        "name": "customer_silver",
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


def _seed_restricted_policy(app, *, authorised_roles=None):
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
            name="restricted-encrypt",
            classification=SecurityLevel.restricted,
            mechanism=ProtectionMechanism.encrypt,
            key_ref_id=key.id,
            authorised_roles=authorised_roles or ["data-engineer", "security-officer"],
            created_by="dev@datafoundry.local",
        )
        sess.add(policy)
        sess.commit()
        return policy.id


class TestScenario5AccessEnforcement:
    def test_column_protections_differ_by_role(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_restricted_policy(app)
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": "email", "policy_id": str(policy_id)},
        )

        # security-officer (in authorised_roles) -> granted raw access.
        officer = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "security-officer@acme.com",
                "resource": f"dataset:{dataset_id}:column:email",
                "action": "read",
            },
        ).json()
        assert officer["outcome"] == "granted"

        # analyst (not in authorised_roles) -> denied (key-use separate).
        analyst = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "analyst@acme.com",
                "resource": f"dataset:{dataset_id}:column:email",
                "action": "read",
            },
        ).json()
        assert analyst["outcome"] == "denied"
        assert "key-use permission" in analyst["reason"]

        # Non-sensitive column (customer_id) has no policy -> granted for all.
        public = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "analyst@acme.com",
                "resource": f"dataset:{dataset_id}:column:customer_id",
                "action": "read",
            },
        ).json()
        assert public["outcome"] == "granted"

    def test_no_cached_grants(self, app, client):
        """Access reflects current authorisation at query time (Edge Case)."""
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_restricted_policy(app)
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": "email", "policy_id": str(policy_id)},
        )

        # analyst denied initially.
        first = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "analyst@acme.com",
                "resource": f"dataset:{dataset_id}:column:email",
                "action": "read",
            },
        ).json()
        assert first["outcome"] == "denied"

        # Grant analyst the role -> next decision reflects it (no cache).
        with app.state.sessionmaker() as sess:
            from datafoundry.controlplane.db.models import ProtectionPolicy

            policy = sess.get(ProtectionPolicy, policy_id)
            policy.authorised_roles = ["data-engineer", "security-officer", "analyst"]
            sess.commit()

        second = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "analyst@acme.com",
                "resource": f"dataset:{dataset_id}:column:email",
                "action": "read",
            },
        ).json()
        assert second["outcome"] == "granted"
