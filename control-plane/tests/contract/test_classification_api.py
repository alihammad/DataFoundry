"""T018: Contract tests for the classification API (security-api.md §1).

Covers:
- POST /datasets/{id}/classification: 201 classification_id/level/policy_id;
  422 invalid level/unknown policy; 403 unauthorised downgrade.
- GET /datasets/{id}/classification: level + per-column protection metadata,
  never key material.
"""

from __future__ import annotations

import uuid

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


def _register_dataset(app, client, platform_id, owner="dev@datafoundry.local"):
    body = {
        "platform_id": str(platform_id),
        "name": "customer_silver",
        "layer": "silver",
        "schema_definition": {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        },
        "owner_identity": owner,
        "classification": "internal",
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _seed_policy(app, mechanism="encrypt", key_ref_id=None):
    from datafoundry.controlplane.db.models import (
        KeyLifecycleState,
        KeyReference,
        KmsProvider,
        ProtectionMechanism,
        ProtectionPolicy,
        SecurityLevel,
    )

    with app.state.sessionmaker() as sess:
        if key_ref_id is None:
            key = KeyReference(
                kms=KmsProvider.aws_kms,
                key_id="alias/restricted",
                version=1,
                lifecycle_state=KeyLifecycleState.active,
                usage_permissions=["data-engineer"],
            )
            sess.add(key)
            sess.flush()
            key_ref_id = key.id
        policy = ProtectionPolicy(
            name="restricted-encrypt",
            classification=SecurityLevel.restricted,
            mechanism=ProtectionMechanism(mechanism),
            key_ref_id=key_ref_id,
            authorised_roles=["data-engineer", "security-officer"],
            created_by="dev@datafoundry.local",
        )
        sess.add(policy)
        sess.commit()
        return policy.id


class TestSetClassification:
    def test_201_shape(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_policy(app)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": None, "policy_id": str(policy_id)},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"classification_id", "level", "policy_id"}
        uuid.UUID(data["classification_id"])
        assert data["level"] == "restricted"

    def test_422_invalid_level(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_policy(app)
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "platinum", "column": None, "policy_id": str(policy_id)},
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_404_unknown_policy(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": None, "policy_id": str(uuid.uuid4())},
        )
        assert response.status_code == 404

    def test_403_unauthorised_downgrade(self, app, client):
        platform_id = _seed_platform(app)
        # Dataset owned by someone else; caller is dev@datafoundry.local.
        dataset_id = _register_dataset(app, client, platform_id, owner="other@acme.com")
        policy_id = _seed_policy(app)
        # First classify as restricted (owner).
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": None, "policy_id": str(policy_id)},
        )
        # Downgrade to internal by non-owner -> 403.
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "internal", "column": None, "policy_id": str(policy_id)},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_permissions"


class TestGetClassification:
    def test_200_with_column_protection(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_policy(app)
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": None, "policy_id": str(policy_id)},
        )
        client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": "email", "policy_id": str(policy_id)},
        )

        response = client.get(f"/api/v1/datasets/{dataset_id}/classification")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["level"] == "restricted"
        assert len(data["columns"]) == 1
        col = data["columns"][0]
        assert col["column"] == "email"
        assert col["mechanism"] == "encrypt"
        assert col["key_ref_id"]  # reference, never material
        assert "data-engineer" in col["authorised_roles"]

    def test_200_unclassified(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        response = client.get(f"/api/v1/datasets/{dataset_id}/classification")
        assert response.status_code == 200
        assert response.json()["level"] == "unclassified"

    def test_404_unknown(self, app, client):
        response = client.get(f"/api/v1/datasets/{uuid.uuid4()}/classification")
        assert response.status_code == 404
