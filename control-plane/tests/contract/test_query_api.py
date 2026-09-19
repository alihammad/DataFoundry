"""T040: Contract tests for the query API (processing-api.md §5).

Covers:
- POST /datasets/{id}/query: 200 columns/rows/row_count; 403 unauthorised.
- POST /datasets/{id}/query/download: CSV/Parquet; column-level protection
  applied.
"""

from __future__ import annotations

import uuid

import pyarrow as pa


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
        "name": "customer_gold",
        "layer": "gold",
        "schema_definition": {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
            "total_amount": {"type": "float", "nullable": True},
        },
        "owner_identity": owner,
        "classification": "internal",
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _seed_gold(app, dataset_id):
    app.state.processing_gateway.seed_table(
        dataset_id,
        "gold",
        pa.schema(
            [
                pa.field("customer_id", pa.int64()),
                pa.field("email", pa.string()),
                pa.field("total_amount", pa.float64()),
            ]
        ),
        [
            {"customer_id": 1, "email": "a@example.com", "total_amount": 30.0},
            {"customer_id": 2, "email": "b@example.com", "total_amount": 5.0},
        ],
    )


class TestQuery:
    def test_200_columns_rows_count(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        _seed_gold(app, dataset_id)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query",
            json={"sql": "SELECT customer_id, total_amount FROM zone"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["columns"] == ["customer_id", "total_amount"]
        assert data["row_count"] == 2
        assert data["rows"][0][0] == 1

    def test_403_unauthorised(self, app, client):
        platform_id = _seed_platform(app)
        # Dataset owned by someone else; caller is dev@datafoundry.local.
        dataset_id = _register_dataset(app, client, platform_id, owner="other@acme.com")
        _seed_gold(app, dataset_id)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query",
            json={"sql": "SELECT * FROM zone"},
        )
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_permissions"

    def test_404_unknown(self, app, client):
        response = client.post(
            f"/api/v1/datasets/{uuid.uuid4()}/query",
            json={"sql": "SELECT * FROM zone"},
        )
        assert response.status_code == 404


class TestQueryDownload:
    def test_csv_with_protection(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        _seed_gold(app, dataset_id)
        # Protect the email column (mask).
        app.state.processing_gateway.protection_policy = {"email": "mask"}

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query/download",
            json={"sql": "SELECT * FROM zone", "format": "csv"},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        body = response.text
        assert "***" in body  # masked email
        assert "a@example.com" not in body

    def test_parquet_with_protection(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        _seed_gold(app, dataset_id)
        app.state.processing_gateway.protection_policy = {"email": "tokenise"}

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query/download",
            json={"sql": "SELECT * FROM zone", "format": "parquet"},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("application/vnd.apache.parquet")

    def test_403_unauthorised_download(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id, owner="other@acme.com")
        _seed_gold(app, dataset_id)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query/download",
            json={"sql": "SELECT * FROM zone", "format": "csv"},
        )
        assert response.status_code == 403
