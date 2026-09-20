"""T028: Contract tests for the tokens API (security-api.md §4).

Covers:
- POST /datasets/{id}/tokens/tokenise: 200 token; deterministic
  same-input-same-token; 403 unauthorised.
- POST /datasets/{id}/tokens/detokenise: 200 value + audited; 403
  unauthorised + recorded (FR-015).
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


def _seed_tokenise_policy(app, *, detokenise_roles=None):
    """Seed a tokenise protection policy + classify the email column."""
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
            name="restricted-tokenise",
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


def _classify_email(app, client, dataset_id, policy_id):
    response = client.post(
        f"/api/v1/datasets/{dataset_id}/classification",
        json={"level": "restricted", "column": "email", "policy_id": str(policy_id)},
    )
    assert response.status_code == 201, response.text


class TestTokenise:
    def test_200_deterministic_same_token(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_tokenise_policy(app)
        _classify_email(app, client, dataset_id, policy_id)

        body = {"column": "email", "value": "a@x.com", "deterministic": True}
        first = client.post(f"/api/v1/datasets/{dataset_id}/tokens/tokenise", json=body)
        second = client.post(f"/api/v1/datasets/{dataset_id}/tokens/tokenise", json=body)
        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["token"] == second.json()["token"]
        assert first.json()["token"].startswith("tok_")

    def test_200_random_distinct(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_tokenise_policy(app)
        _classify_email(app, client, dataset_id, policy_id)

        body = {"column": "email", "value": "a@x.com", "deterministic": False}
        first = client.post(f"/api/v1/datasets/{dataset_id}/tokens/tokenise", json=body).json()[
            "token"
        ]
        second = client.post(f"/api/v1/datasets/{dataset_id}/tokens/tokenise", json=body).json()[
            "token"
        ]
        assert first != second

    def test_403_unauthorised_tokenise(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        # Policy whose authorised_roles excludes the dev caller's roles.
        policy_id = _seed_tokenise_policy(app)
        with app.state.sessionmaker() as sess:
            from datafoundry.controlplane.db.models import ProtectionPolicy

            policy = sess.get(ProtectionPolicy, policy_id)
            policy.authorised_roles = ["analyst"]
            sess.commit()
        _classify_email(app, client, dataset_id, policy_id)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tokens/tokenise",
            json={"column": "email", "value": "a@x.com", "deterministic": True},
        )
        assert response.status_code == 403
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["code"] == "insufficient_permissions"

    def test_404_unknown_dataset(self, app, client):
        response = client.post(
            f"/api/v1/datasets/{uuid.uuid4()}/tokens/tokenise",
            json={"column": "email", "value": "a@x.com", "deterministic": True},
        )
        assert response.status_code == 404


class TestDetokenise:
    def test_200_value_audited(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_tokenise_policy(app)
        _classify_email(app, client, dataset_id, policy_id)

        token = client.post(
            f"/api/v1/datasets/{dataset_id}/tokens/tokenise",
            json={"column": "email", "value": "a@x.com", "deterministic": True},
        ).json()["token"]

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tokens/detokenise",
            json={"column": "email", "token": token, "purpose": "approved-analytics"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["value"] == "a@x.com"

        # Audited (FR-012).
        with app.state.sessionmaker() as sess:
            from datafoundry.controlplane.db.models import SecurityAuditRecord

            records = (
                sess.query(SecurityAuditRecord)
                .filter_by(action="security.detokenise", result="success")
                .all()
            )
            assert any(r.purpose == "approved-analytics" for r in records)

    def test_403_unauthorised_recorded(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        # detokenise_roles excludes the dev caller's roles.
        policy_id = _seed_tokenise_policy(app, detokenise_roles=["analyst"])
        _classify_email(app, client, dataset_id, policy_id)

        token = client.post(
            f"/api/v1/datasets/{dataset_id}/tokens/tokenise",
            json={"column": "email", "value": "a@x.com", "deterministic": True},
        ).json()["token"]

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tokens/detokenise",
            json={"column": "email", "token": token, "purpose": "approved-analytics"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_permissions"

        # Attempt recorded (FR-015).
        with app.state.sessionmaker() as sess:
            from datafoundry.controlplane.db.models import SecurityAuditRecord

            records = (
                sess.query(SecurityAuditRecord)
                .filter_by(action="security.detokenise", result="denied")
                .all()
            )
            assert len(records) == 1

    def test_404_unknown_token(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        policy_id = _seed_tokenise_policy(app)
        _classify_email(app, client, dataset_id, policy_id)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/tokens/detokenise",
            json={"column": "email", "token": "tok_nope", "purpose": "approved-analytics"},
        )
        assert response.status_code == 404
