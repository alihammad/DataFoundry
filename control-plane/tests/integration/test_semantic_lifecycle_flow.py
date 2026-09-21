"""T023: Integration test for quickstart Scenario 2 (US2, FR-003/004/005).

Submit a metric change that fails a semantic test -> publication blocked with
failure detail; submit a correct change -> publishes with version history;
query "as of" a prior period records the definition version (FR-012, US2-AC3).
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


def _define_test(app, client, model_id, *, expected_value, category="calculation"):
    params = {
        "calculation": {"reference_data": "orders_ref", "expected_value": expected_value},
        "relationship": {"relationship": "orders_customer", "max_fanout": 1},
    }[category]
    response = client.post(
        f"/api/v1/semantic/models/{model_id}/tests",
        json={"tests": [{"name": f"test_{category}", "category": category, "parameters": params}]},
    )
    assert response.status_code == 201, response.text
    return response.json()["test_id"]


class TestScenario2GovernedLifecycle:
    def test_failed_test_blocks_publication(self, app, client):
        platform_id = _seed_platform(app)
        _seed_dataset(app, platform_id, name="orders", layer="gold")
        model_id = client.post("/api/v1/semantic/models", json=VALID_MODEL).json()["model_id"]
        # Test expects 9999 but actual is 525 -> fails.
        _define_test(app, client, model_id, expected_value=9999.0)

        response = client.post(
            f"/api/v1/semantic/models/{model_id}/publish",
            json={"change_classification": "non_breaking"},
        )
        assert response.status_code == 422, response.text
        assert response.json()["errors"][0]["code"] == "tests_failed"

    def test_correct_change_publishes_with_history(self, app, client):
        platform_id = _seed_platform(app)
        _seed_dataset(app, platform_id, name="orders", layer="gold")
        model_id = client.post("/api/v1/semantic/models", json=VALID_MODEL).json()["model_id"]
        # Test expects 525 (matches actual) -> passes.
        _define_test(app, client, model_id, expected_value=525.0)

        proposed = client.post(
            f"/api/v1/semantic/models/{model_id}/publish",
            json={"change_classification": "non_breaking"},
        )
        assert proposed.status_code == 201, proposed.text
        publication_id = proposed.json()["publication_id"]

        approved = client.post(f"/api/v1/publications/{publication_id}/approve", json={})
        assert approved.status_code == 200, approved.text
        assert approved.json()["approval_status"] == "approved"
        assert approved.json()["published_at"]

        # Version history (US2-AC2).
        history = client.get(f"/api/v1/semantic/models/{model_id}/publications").json()
        assert len(history["items"]) == 1
        assert history["items"][0]["approval_status"] == "approved"

    def test_query_records_definition_version(self, app, client):
        platform_id = _seed_platform(app)
        _seed_dataset(app, platform_id, name="orders", layer="gold")
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

        result = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}, "as_of": "2026-08-01"},
        ).json()
        # Definition version recorded with the result (FR-012, US2-AC3).
        assert result["definition_version"] == 1
        assert result["value"] == 525.0
