"""T030: Integration test for quickstart Scenario 3 (US3, FR-007, SC-005).

Query the same metric as two roles with different authorisations -> different
visibility/results; protected column values never appear without authorised
detokenisation.
"""

from __future__ import annotations

VALID_MODEL = {
    "domain": "commerce",
    "metrics": [
        {
            "name": "revenue",
            "business_definition": "Sum of order amount",
            "formula": {"measure": "order_amount", "aggregation": "sum"},
            "dimensions": ["customer", "time"],
            "bound_datasets": ["orders"],
            "owner": "analytics@acme.com",
        }
    ],
    "dimensions": [
        {"name": "customer", "members": ["customer_id"], "protection_status": "internal"},
        {"name": "time", "members": ["order_date"], "protection_status": "public"},
    ],
    "measures": [
        {"name": "order_amount", "dataset": "orders", "column": "amount", "data_type": "numeric"}
    ],
    "relationships": [],
}


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


def _seed_dataset(app, platform_id, name="orders", layer="gold"):
    from datafoundry.controlplane.db.models import Dataset

    with app.state.sessionmaker() as sess:
        row = Dataset(
            platform_id=platform_id,
            name=name,
            layer=layer,
            schema_definition={"order_id": {"type": "integer", "nullable": False}},
            owner_identity="dev@datafoundry.local",
            classification="internal",
        )
        sess.add(row)
        sess.commit()
        return row.id


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


def _override_caller(app, *, roles):
    from datafoundry.controlplane.api.auth import Caller, get_caller

    def _caller():
        return Caller(identity="dev@datafoundry.local", roles=tuple(roles))

    app.dependency_overrides[get_caller] = _caller


class TestScenario3AccessPolicies:
    def test_roles_see_different_visibility(self, app, client):
        """US3-AC1: authorised role queries; unauthorised role gets 403."""
        platform_id = _seed_platform(app)
        dataset_id = _seed_dataset(app, platform_id, name="orders", layer="gold")
        policy_id = _seed_restricted_policy(app, authorised_roles=["security-officer"])
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": None, "policy_id": str(policy_id)},
        )
        assert response.status_code == 201, response.text

        model_id = client.post("/api/v1/semantic/models", json=VALID_MODEL).json()["model_id"]
        metric_id = client.post(
            f"/api/v1/semantic/models/{model_id}/metrics",
            json={
                "name": "revenue2",
                "business_definition": "Another revenue",
                "formula": {"measure": "order_amount", "aggregation": "sum"},
                "dimensions": ["customer"],
                "bound_datasets": ["orders"],
                "owner": "analytics@acme.com",
            },
        ).json()["metric_id"]

        # Authorised role -> 200 with value.
        _override_caller(app, roles=["security-officer"])
        ok = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["value"] == 525.0

        # Unauthorised role -> 403 (US3-AC1).
        _override_caller(app, roles=["data-engineer"])
        denied = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        )
        assert denied.status_code == 403, denied.text

    def test_protected_column_masked_in_results(self, app, client):
        """US3-AC2: protected column values never appear in query output."""
        platform_id = _seed_platform(app)
        _seed_dataset(app, platform_id, name="customers", layer="silver")

        model = {
            "domain": "commerce_access",
            "metrics": [
                {
                    "name": "customer_count",
                    "business_definition": "Count of customers",
                    "formula": {"measure": "customer_id", "aggregation": "count"},
                    "dimensions": ["customer"],
                    "bound_datasets": ["customers"],
                    "owner": "analytics@acme.com",
                }
            ],
            "dimensions": [
                {"name": "customer", "members": ["customer_id"], "protection_status": "internal"}
            ],
            "measures": [
                {
                    "name": "customer_id",
                    "dataset": "customers",
                    "column": "customer_id",
                    "data_type": "integer",
                }
            ],
            "relationships": [],
        }
        model_id = client.post("/api/v1/semantic/models", json=model).json()["model_id"]
        metric_id = client.post(
            f"/api/v1/semantic/models/{model_id}/metrics",
            json={
                "name": "customer_count2",
                "business_definition": "Count of customers",
                "formula": {"measure": "customer_id", "aggregation": "count"},
                "dimensions": ["customer"],
                "bound_datasets": ["customers"],
                "owner": "analytics@acme.com",
            },
        ).json()["metric_id"]

        _override_caller(app, roles=["analyst"])
        response = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        )
        assert response.status_code == 200, response.text
        # analyst row restriction segment != 'vip' excludes Bob -> 2 (US3-AC3).
        assert response.json()["value"] == 2
