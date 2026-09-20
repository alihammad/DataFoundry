"""T036: Contract tests for the access API (security-api.md §5).

Covers:
- POST /access/decide: 200 outcome granted/denied with
  classification_consulted/policy_applied/reason; key-use permission
  separately enforced from data-read (FR-013).
"""

from __future__ import annotations

PROBLEM_CT = "application/problem+json"


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
    """Seed a restricted encrypt policy + classify the email column."""
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


def _classify_email(app, client, dataset_id, policy_id):
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/classification",
        json={"level": "restricted", "column": "email", "policy_id": str(policy_id)},
    )
    assert response.status_code == 201, response.text


class TestAccessDecide:
    def test_200_granted_for_authorised_role(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_restricted_policy(app)
        _classify_email(app, client, dataset_id, policy_id)

        # security-officer is in authorised_roles -> granted.
        response = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "security-officer@acme.com",
                "resource": f"dataset:{dataset_id}:column:email",
                "action": "read",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["outcome"] == "granted"
        assert data["classification_consulted"] == "restricted"
        assert data["policy_applied"] == str(policy_id)
        assert data["reason"] is None

    def test_200_denied_for_unauthorised_role(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_restricted_policy(app)
        _classify_email(app, client, dataset_id, policy_id)

        # analyst is NOT in authorised_roles -> denied (key-use separate).
        response = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "analyst@acme.com",
                "resource": f"dataset:{dataset_id}:column:email",
                "action": "read",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["outcome"] == "denied"
        assert data["classification_consulted"] == "restricted"
        assert data["policy_applied"] == str(policy_id)
        assert "key-use permission" in data["reason"]

    def test_200_granted_unclassified_dataset(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)

        # No classification -> public, granted.
        response = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "analyst@acme.com",
                "resource": f"dataset:{dataset_id}:column:email",
                "action": "read",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["outcome"] == "granted"
        assert data["classification_consulted"] == "public"

    def test_422_invalid_resource(self, app, client):
        response = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "analyst@acme.com",
                "resource": "table:foo",
                "action": "read",
            },
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_422_invalid_dataset_uuid(self, app, client):
        response = client.post(
            "/api/v1/access/decide",
            json={
                "identity": "analyst@acme.com",
                "resource": "dataset:not-a-uuid:column:email",
                "action": "read",
            },
        )
        assert response.status_code == 422
        assert response.json()["errors"]
