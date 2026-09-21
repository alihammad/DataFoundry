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
