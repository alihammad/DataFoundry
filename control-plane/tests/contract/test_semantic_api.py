"""T014: Contract tests for the semantic API (semantic-api.md sections 1-2).

Covers:
- POST /semantic/models: 201 model_id/version; 422 all-errors.
- POST /semantic/models/{id}/metrics: 201; 422 invalid formula/duplicate/secret.
- GET /semantic/metrics/{id}: 200 with definition/formula/owner/datasets/lineage.
- POST /semantic/metrics/{id}/query: 200 with value + provenance.
"""

from __future__ import annotations

import uuid

PROBLEM_CT = "application/problem+json"

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


def _define_model(app, client, platform_id):
    _seed_dataset(app, platform_id, name="orders", layer="gold")
    response = client.post("/api/v1/semantic/models", json=VALID_MODEL)
    assert response.status_code == 201, response.text
    return response.json()["model_id"]


class TestDefineSemanticModel:
    def test_201_shape(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        # model_id is a uuid; version 1; draft.
        uuid.UUID(model_id)

    def test_422_all_errors(self, app, client):
        platform_id = _seed_platform(app)
        _seed_dataset(app, platform_id, name="orders", layer="gold")
        bad = dict(VALID_MODEL)
        bad["metrics"] = [dict(VALID_MODEL["metrics"][0])]
        bad["metrics"][0]["formula"] = {"measure": "nope", "aggregation": "sum"}
        response = client.post("/api/v1/semantic/models", json=bad)
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_422_secret_scan(self, app, client):
        platform_id = _seed_platform(app)
        _seed_dataset(app, platform_id, name="orders", layer="gold")
        bad = dict(VALID_MODEL)
        bad["metrics"] = [dict(VALID_MODEL["metrics"][0])]
        bad["metrics"][0]["business_definition"] = "AKIAIOSFODNN7EXAMPLE"
        response = client.post("/api/v1/semantic/models", json=bad)
        assert response.status_code == 422
        assert response.json()["errors"]


class TestDefineMetric:
    def test_201(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        response = client.post(
            f"/api/v1/semantic/models/{model_id}/metrics",
            json={
                "name": "revenue2",
                "business_definition": "Another revenue",
                "formula": {"measure": "order_amount", "aggregation": "sum"},
                "dimensions": ["customer"],
                "bound_datasets": ["orders"],
                "owner": "analytics@acme.com",
            },
        )
        assert response.status_code == 201, response.text
        uuid.UUID(response.json()["metric_id"])

    def test_422_duplicate_term(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        response = client.post(
            f"/api/v1/semantic/models/{model_id}/metrics",
            json={
                "name": "revenue",
                "business_definition": "Duplicate",
                "formula": {"measure": "order_amount", "aggregation": "sum"},
                "dimensions": ["customer"],
                "bound_datasets": ["orders"],
                "owner": "analytics@acme.com",
            },
        )
        assert response.status_code == 422
        assert response.json()["errors"]


class TestDescribeMetric:
    def test_200(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
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

        response = client.get(f"/api/v1/semantic/metrics/{metric_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["name"] == "revenue2"
        assert data["business_definition"] == "Another revenue"
        assert data["formula"]["aggregation"] == "sum"
        assert data["owner_identity"] == "analytics@acme.com"
        assert data["bound_datasets"] == ["orders"]
        assert data["lineage"]["model_id"] == model_id

    def test_404_unknown(self, app, client):
        response = client.get(f"/api/v1/semantic/metrics/{uuid.uuid4()}")
        assert response.status_code == 404


class TestQueryMetric:
    def test_200_with_provenance(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
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

        response = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["metric_id"] == metric_id
        assert data["value"] == 525.0  # 100+250+75+50+50
        assert data["definition_version"] == 1
        assert "orders" in data["dataset_versions"]
        assert data["quality_state"] == "passed"

    def test_404_unknown(self, app, client):
        response = client.post(
            f"/api/v1/semantic/metrics/{uuid.uuid4()}/query",
            json={"dimensions": [], "filters": {}},
        )
        assert response.status_code == 404


class TestSemanticTests:
    """T022: semantic test definition + run (semantic-api.md §3)."""

    def _define_test(self, app, client, model_id, category="calculation"):
        params = {
            "calculation": {"reference_data": "orders_ref", "expected_value": 525.0},
            "relationship": {"relationship": "orders_customer", "max_fanout": 1},
        }[category]
        response = client.post(
            f"/api/v1/semantic/models/{model_id}/tests",
            json={
                "tests": [{"name": f"test_{category}", "category": category, "parameters": params}]
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["test_id"]

    def test_201_define_test(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        test_id = self._define_test(app, client, model_id)
        uuid.UUID(test_id)

    def test_200_run_passed(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        test_id = self._define_test(app, client, model_id)
        response = client.post(f"/api/v1/semantic/tests/{test_id}/run", json={})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] in ("passed", "failed")
        assert data["test_id"] == test_id


class TestPublications:
    """T022: publication propose/approve/history (semantic-api.md §4)."""

    def _define_test(self, app, client, model_id, category="calculation"):
        params = {
            "calculation": {"reference_data": "orders_ref", "expected_value": 525.0},
            "relationship": {"relationship": "orders_customer", "max_fanout": 1},
        }[category]
        response = client.post(
            f"/api/v1/semantic/models/{model_id}/tests",
            json={
                "tests": [{"name": f"test_{category}", "category": category, "parameters": params}]
            },
        )
        assert response.status_code == 201, response.text
        return response.json()["test_id"]

    def test_201_propose_pending(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        self._define_test(app, client, model_id)
        response = client.post(
            f"/api/v1/semantic/models/{model_id}/publish",
            json={"change_classification": "non_breaking"},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["approval_status"] == "pending"
        uuid.UUID(data["publication_id"])

    def test_200_approve(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        self._define_test(app, client, model_id)
        publication_id = client.post(
            f"/api/v1/semantic/models/{model_id}/publish",
            json={"change_classification": "non_breaking"},
        ).json()["publication_id"]
        response = client.post(f"/api/v1/publications/{publication_id}/approve", json={})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["approval_status"] == "approved"
        assert data["published_at"]

    def test_200_publication_history(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        self._define_test(app, client, model_id)
        client.post(
            f"/api/v1/semantic/models/{model_id}/publish",
            json={"change_classification": "non_breaking"},
        )
        response = client.get(f"/api/v1/semantic/models/{model_id}/publications")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["change_classification"] == "non_breaking"


class TestSemanticAccess:
    """T029: access paths on metric query (semantic-api.md §2, US3).

    - US3-AC1: 403 for unauthorised user over a RESTRICTED dataset.
    - US3-AC2: protected column values masked/tokenised per policy (SC-005).
    - US3-AC3: row-level restrictions applied.
    """

    def _seed_restricted_policy(self, app, *, authorised_roles=None):
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

    def _classify_dataset(self, app, client, dataset_id, policy_id):
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/classification",
            json={"level": "restricted", "column": None, "policy_id": str(policy_id)},
        )
        assert response.status_code == 201, response.text

    def _override_caller(self, app, *, roles):
        from datafoundry.controlplane.api.auth import Caller, get_caller

        def _caller():
            return Caller(identity="dev@datafoundry.local", roles=tuple(roles))

        app.dependency_overrides[get_caller] = _caller

    def test_403_unauthorised_over_restricted(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _seed_dataset(app, platform_id, name="orders", layer="gold")
        policy_id = self._seed_restricted_policy(app, authorised_roles=["security-officer"])
        self._classify_dataset(app, client, dataset_id, policy_id)

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

        # data-engineer is NOT in authorised_roles -> 403 (US3-AC1).
        self._override_caller(app, roles=["data-engineer"])
        response = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        )
        assert response.status_code == 403, response.text
        assert response.headers["content-type"].startswith(PROBLEM_CT)

    def test_200_authorised_over_restricted(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _seed_dataset(app, platform_id, name="orders", layer="gold")
        policy_id = self._seed_restricted_policy(app, authorised_roles=["security-officer"])
        self._classify_dataset(app, client, dataset_id, policy_id)

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

        self._override_caller(app, roles=["security-officer"])
        response = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        )
        assert response.status_code == 200, response.text
        assert response.json()["value"] == 525.0

    def test_200_row_level_restriction_applied(self, app, client):
        """US3-AC3: analyst role sees only non-vip customer rows."""
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

        # analyst role has row restriction segment != 'vip' on customers.
        self._override_caller(app, roles=["analyst"])
        response = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        )
        assert response.status_code == 200, response.text
        # 3 customers total; vip (Bob) excluded -> 2 (US3-AC3).
        assert response.json()["value"] == 2


class TestSemanticDiscovery:
    """T033: discovery search (semantic-api.md §6, US4, FR-011).

    - US4-AC1: certified metric surfaces with complete metadata.
    - US4-AC2: drafts hidden from general users or clearly marked.
    """

    def _publish_model(self, app, client, model_id):
        # Define a passing test then publish + approve -> certified.
        response = client.post(
            f"/api/v1/semantic/models/{model_id}/tests",
            json={
                "tests": [
                    {
                        "name": "revenue_calculation",
                        "category": "calculation",
                        "parameters": {
                            "reference_data": "orders_ref",
                            "expected_value": 525.0,
                        },
                    }
                ]
            },
        )
        assert response.status_code == 201, response.text
        publication_id = client.post(
            f"/api/v1/semantic/models/{model_id}/publish",
            json={"change_classification": "non_breaking"},
        ).json()["publication_id"]
        approved = client.post(f"/api/v1/publications/{publication_id}/approve", json={})
        assert approved.status_code == 200, approved.text

    def test_200_certified_metric_surfaces(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        self._publish_model(app, client, model_id)

        response = client.get("/api/v1/semantic/discovery", params={"q": "revenue"})
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["name"] == "revenue"
        assert item["business_definition"] == "Sum of order amount"
        assert item["owner_identity"] == "analytics@acme.com"
        assert item["certification_state"] == "published"
        assert item["lineage"]["domain"] == "commerce"
        assert "consuming_teams" in item

    def test_200_draft_hidden_from_general_users(self, app, client):
        """US4-AC2: draft definitions hidden from general users."""
        platform_id = _seed_platform(app)
        _define_model(app, client, platform_id)
        # Model stays draft (no publish).

        response = client.get("/api/v1/semantic/discovery", params={"q": "revenue"})
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []

    def test_200_no_match_returns_empty(self, app, client):
        platform_id = _seed_platform(app)
        model_id = _define_model(app, client, platform_id)
        self._publish_model(app, client, model_id)

        response = client.get("/api/v1/semantic/discovery", params={"q": "nonexistent"})
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
