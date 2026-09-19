"""T041: Integration test for quickstart Scenario 5 (US5, FR-016).

Query a CONSUMABLE Gold dataset, verify results reflect current version; query
unauthorised dataset -> 403; download respects column-level protection
(masked/tokenised per policy).
"""

from __future__ import annotations

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


def _seed_gold(app, dataset_id, rows):
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
        rows,
    )


class TestScenario5Query:
    def test_query_reflects_current_version(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        _seed_gold(
            app,
            dataset_id,
            [
                {"customer_id": 1, "email": "a@example.com", "total_amount": 30.0},
                {"customer_id": 2, "email": "b@example.com", "total_amount": 5.0},
            ],
        )

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query",
            json={"sql": "SELECT customer_id, total_amount FROM zone ORDER BY customer_id"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["row_count"] == 2
        assert data["rows"][0] == [1, 30.0]
        assert data["rows"][1] == [2, 5.0]

        # Update the version (new snapshot) -> query reflects it.
        _seed_gold(
            app,
            dataset_id,
            [
                {"customer_id": 1, "email": "a@example.com", "total_amount": 99.0},
            ],
        )
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query",
            json={"sql": "SELECT total_amount FROM zone"},
        )
        assert response.status_code == 200
        assert response.json()["rows"] == [[99.0]]

    def test_unauthorised_query_403(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id, owner="other@acme.com")
        _seed_gold(
            app, dataset_id, [{"customer_id": 1, "email": "a@example.com", "total_amount": 1.0}]
        )

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query",
            json={"sql": "SELECT * FROM zone"},
        )
        assert response.status_code == 403

    def test_download_respects_protection(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        _seed_gold(
            app,
            dataset_id,
            [
                {"customer_id": 1, "email": "a@example.com", "total_amount": 30.0},
                {"customer_id": 2, "email": "b@example.com", "total_amount": 5.0},
            ],
        )
        # Mask email, tokenise customer_id.
        app.state.processing_gateway.protection_policy = {
            "email": "mask",
            "customer_id": "tokenise",
        }

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/query/download",
            json={"sql": "SELECT * FROM zone", "format": "csv"},
        )
        assert response.status_code == 200, response.text
        body = response.text
        assert "***" in body  # masked email
        assert "a@example.com" not in body
        assert "tok_1" in body  # tokenised customer_id
        assert "tok_2" in body
