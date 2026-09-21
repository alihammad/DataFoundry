"""T034: Integration test for quickstart Scenario 4 (US4, FR-011).

Search a business term -> certified metric surfaces with complete metadata;
draft definitions clearly distinguished (hidden from general users).
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


def _publish_model(app, client, model_id):
    response = client.post(
        f"/api/v1/semantic/models/{model_id}/tests",
        json={
            "tests": [
                {
                    "name": "revenue_calculation",
                    "category": "calculation",
                    "parameters": {"reference_data": "orders_ref", "expected_value": 525.0},
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


class TestScenario4Discovery:
    def test_certified_metric_surfaces_with_metadata(self, app, client):
        platform_id = _seed_platform(app)
        _seed_dataset(app, platform_id, name="orders", layer="gold")
        model_id = client.post("/api/v1/semantic/models", json=VALID_MODEL).json()["model_id"]
        _publish_model(app, client, model_id)

        response = client.get("/api/v1/semantic/discovery", params={"q": "customer revenue"})
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

    def test_draft_hidden_from_general_users(self, app, client):
        platform_id = _seed_platform(app)
        _seed_dataset(app, platform_id, name="orders", layer="gold")
        client.post("/api/v1/semantic/models", json=VALID_MODEL)
        # Model stays draft.

        response = client.get("/api/v1/semantic/discovery", params={"q": "revenue"})
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
