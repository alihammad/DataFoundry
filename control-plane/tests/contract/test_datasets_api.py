"""T014: Contract tests for the datasets API (processing-api.md §1).

Covers:
- POST /datasets: 201 {dataset_id}; 422 all-errors (unknown layer, bad name,
  missing owner, secret-scan hit); 409 duplicate (platform_id, name).
- GET /datasets: list with promotion_state + quality_score.
- GET /datasets/{id}: detail with promotion_state + gate results + transition.
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


def _valid_dataset(**overrides):
    body = {
        "platform_id": str(uuid.uuid4()),
        "name": "customer_silver",
        "layer": "silver",
        "schema_definition": {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        },
        "owner_identity": "user@acme.com",
        "classification": "internal",
    }
    body.update(overrides)
    return body


class TestRegisterDataset:
    def test_201_shape(self, app, client):
        platform_id = _seed_platform(app)
        response = client.post(
            "/api/v1/datasets", json=_valid_dataset(platform_id=str(platform_id))
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"dataset_id"}
        uuid.UUID(data["dataset_id"])

    def test_audit_written(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        platform_id = _seed_platform(app)
        assert (
            client.post(
                "/api/v1/datasets", json=_valid_dataset(platform_id=str(platform_id))
            ).status_code
            == 201
        )
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "dataset.registered" in actions

    def test_unknown_layer_422(self, app, client):
        platform_id = _seed_platform(app)
        response = client.post(
            "/api/v1/datasets",
            json=_valid_dataset(platform_id=str(platform_id), layer="platinum"),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_bad_name_422(self, app, client):
        platform_id = _seed_platform(app)
        response = client.post(
            "/api/v1/datasets",
            json=_valid_dataset(platform_id=str(platform_id), name="Bad Name!"),
        )
        assert response.status_code == 422
        assert response.json()["errors"]

    def test_missing_owner_422(self, app, client):
        platform_id = _seed_platform(app)
        body = _valid_dataset(platform_id=str(platform_id))
        del body["owner_identity"]
        response = client.post("/api/v1/datasets", json=body)
        assert response.status_code == 422
        assert response.json()["errors"]

    def test_secret_scan_hit_422(self, app, client):
        platform_id = _seed_platform(app)
        body = _valid_dataset(platform_id=str(platform_id))
        body["description"] = "AKIAIOSFODNN7EXAMPLE"
        response = client.post("/api/v1/datasets", json=body)
        assert response.status_code == 422
        assert response.json()["errors"]

    def test_duplicate_409(self, app, client):
        platform_id = _seed_platform(app)
        body = _valid_dataset(platform_id=str(platform_id))
        assert client.post("/api/v1/datasets", json=body).status_code == 201
        response = client.post("/api/v1/datasets", json=body)
        assert response.status_code == 409
        assert response.json()["code"] == "name_taken"


class TestListDatasets:
    def test_200_shape(self, app, client):
        platform_id = _seed_platform(app)
        client.post("/api/v1/datasets", json=_valid_dataset(platform_id=str(platform_id)))
        response = client.get("/api/v1/datasets")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["name"] == "customer_silver"
        assert item["layer"] == "silver"
        assert item["owner"] == "user@acme.com"
        assert item["classification"] == "internal"
        assert item["promotion_state"] is None
        assert item["quality_score"] is None


class TestDatasetDetail:
    def test_200_with_promotion_state(self, app, client):
        from datafoundry.controlplane.db.models import PromotionState, PromotionStateRow

        platform_id = _seed_platform(app)
        dataset_id = client.post(
            "/api/v1/datasets", json=_valid_dataset(platform_id=str(platform_id))
        ).json()["dataset_id"]
        with app.state.sessionmaker() as sess:
            sess.add(
                PromotionStateRow(
                    dataset_id=uuid.UUID(dataset_id),
                    state=PromotionState.silver_validated,
                )
            )
            sess.commit()

        response = client.get(f"/api/v1/datasets/{dataset_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["dataset_id"] == dataset_id
        assert data["promotion_state"] == "silver_validated"
        assert data["schema_definition"]["customer_id"]["type"] == "integer"

    def test_404_unknown(self, app, client):
        response = client.get(f"/api/v1/datasets/{uuid.uuid4()}")
        assert response.status_code == 404
