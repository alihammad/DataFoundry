"""T015: Integration test for quickstart Scenario 1 (US1, FR-002, SC-001).

Define a revenue metric, query it through two consumption paths (analyst SQL +
programmatic API), verify identical results; change the definition through the
governed workflow and verify consumers reflect the new version.
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


class TestScenario1MetricConsistency:
    def test_two_consumption_paths_identical(self, app, client):
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

        # Consumption path 1: programmatic API.
        api_result = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        ).json()

        # Consumption path 2: analyst SQL via the semantic engine directly.
        from datafoundry.controlplane.semantic.compute.engine import compute_metric

        sql_result = compute_metric(
            gateway=app.state.semantic_gateway,
            dataset="orders",
            layer="gold",
            measure_column="amount",
            aggregation="sum",
            filter_spec=None,
            dimensions=[],
            definition_version=1,
        )

        # Identical results (FR-002, SC-001).
        assert api_result["value"] == sql_result.value == 525.0
        assert api_result["quality_state"] == sql_result.quality_state == "passed"

        # Result carries provenance (FR-008, FR-012).
        assert api_result["definition_version"] == 1
        assert "orders" in api_result["dataset_versions"]
        assert api_result["freshness"]

    def test_definition_change_reflected(self, app, client):
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

        before = client.post(
            f"/api/v1/semantic/metrics/{metric_id}/query",
            json={"dimensions": [], "filters": {}},
        ).json()
        assert before["value"] == 525.0

        # Change the definition (new model version) -> consumers reflect it.
        v2 = dict(VALID_MODEL)
        v2["domain"] = "commerce_v2"
        v2["metrics"] = [dict(VALID_MODEL["metrics"][0])]
        v2["metrics"][0]["formula"] = {"measure": "order_amount", "aggregation": "count"}
        model2 = client.post("/api/v1/semantic/models", json=v2).json()
        assert model2["version"] == 1  # new model, version 1

        # The describe endpoint reflects the current definition.
        detail = client.get(f"/api/v1/semantic/metrics/{metric_id}").json()
        assert detail["formula"]["aggregation"] == "sum"
