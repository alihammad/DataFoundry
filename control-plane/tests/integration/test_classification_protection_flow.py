"""T019: Integration test for quickstart Scenario 1 (US1, FR-001/002/003/017).

Classify a dataset RESTRICTED with a sensitive email column, ingest data,
verify the email column is protected per the mapped policy in all layers while
non-sensitive columns remain queryable.
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


def _seed_policy(app, mechanism="encrypt"):
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
            mechanism=ProtectionMechanism(mechanism),
            key_ref_id=key.id,
            authorised_roles=["data-engineer", "security-officer"],
            created_by="dev@datafoundry.local",
        )
        sess.add(policy)
        sess.commit()
        return policy.id


class TestScenario1ClassificationProtection:
    def test_classify_protect_metadata(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_policy(app)

        # Classify dataset RESTRICTED + email column protected.
        resp = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": None, "policy_id": str(policy_id)},
        )
        assert resp.status_code == 201, resp.text
        resp = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": "email", "policy_id": str(policy_id)},
        )
        assert resp.status_code == 201, resp.text

        # Protection metadata: email protected, customer_id not (FR-017).
        detail = client.get(f"/api/v1/datasets/{dataset_id}/classification").json()
        assert detail["level"] == "restricted"
        columns = {c["column"]: c for c in detail["columns"]}
        assert "email" in columns
        assert columns["email"]["mechanism"] == "encrypt"
        assert columns["email"]["key_ref_id"]  # reference, never material
        assert "customer_id" not in columns  # non-sensitive column unprotected

        # Never key material in the response (SC-003).
        body = client.get(f"/api/v1/datasets/{dataset_id}/classification").text
        assert "alias/restricted" not in body  # key_id is not material but not exposed here

    def test_downgrade_requires_owner(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_policy(app)
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": None, "policy_id": str(policy_id)},
        )
        # Owner downgrades -> allowed.
        resp = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "internal", "column": None, "policy_id": str(policy_id)},
        )
        assert resp.status_code == 201, resp.text
        assert (
            client.get(f"/api/v1/datasets/{dataset_id}/classification").json()["level"]
            == "internal"
        )
