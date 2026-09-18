"""T021: Contract tests for the transformations API (processing-api.md §2).

Covers:
- POST /transformations: 201 {transformation_id, version}; 422 all-errors
  (invalid source/target layer, bad logic, secret-scan hit).
- GET /transformations/{id}: logic_definition + logic_hash.
- POST /transformations/{id}/run: output_version, record_count,
  quarantined_count, gate_report_id, promotion_state.
- GET /transformations/{id}/runs: run history.
"""

from __future__ import annotations

import uuid

import pyarrow as pa

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


def _register_dataset(
    app, client, platform_id, name="customer_silver", layer="silver", schema_definition=None
):
    body = {
        "platform_id": str(platform_id),
        "name": name,
        "layer": layer,
        "schema_definition": schema_definition
        or {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        },
        "owner_identity": "user@acme.com",
        "classification": "internal",
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _valid_transform(**overrides):
    body = {
        "name": "customer_silver_transform",
        "source_layer": "bronze",
        "target_layer": "silver",
        "dedup_keys": ["customer_id"],
        "reconciliation_tolerance": 0.5,
        "logic": {
            "type": "silver",
            "cleansing": [{"column": "email", "op": "trim"}],
            "standardisation": [{"column": "country", "op": "upper"}],
            "schema_enforcement": {
                "customer_id": {"type": "integer", "nullable": False},
                "email": {"type": "string", "nullable": False},
            },
        },
    }
    body.update(overrides)
    return body


class TestDefineTransformation:
    def test_201_shape(self, app, client):
        response = client.post("/api/v1/transformations", json=_valid_transform())
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"transformation_id", "version"}
        uuid.UUID(data["transformation_id"])
        assert data["version"] == 1

    def test_version_increments_per_name(self, app, client):
        first = client.post("/api/v1/transformations", json=_valid_transform())
        assert first.status_code == 201
        second = client.post(
            "/api/v1/transformations",
            json=_valid_transform(logic={"type": "silver", "cleansing": [], "standardisation": []}),
        )
        assert second.status_code == 201
        assert second.json()["version"] == 2

    def test_audit_written(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        assert client.post("/api/v1/transformations", json=_valid_transform()).status_code == 201
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "transformation.defined" in actions

    def test_invalid_source_target_422(self, app, client):
        response = client.post(
            "/api/v1/transformations",
            json=_valid_transform(source_layer="gold", target_layer="silver"),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_bad_logic_422(self, app, client):
        response = client.post(
            "/api/v1/transformations",
            json=_valid_transform(logic={"type": "silver", "cleansing": "not-a-list"}),
        )
        assert response.status_code == 422
        assert response.json()["errors"]

    def test_secret_scan_hit_422(self, app, client):
        body = _valid_transform()
        body["logic"]["schema_enforcement"]["password"] = {
            "type": "AKIAIOSFODNN7EXAMPLE",
            "nullable": False,
        }
        response = client.post("/api/v1/transformations", json=body)
        assert response.status_code == 422
        assert response.json()["errors"]


class TestGetTransformation:
    def test_200_logic_definition_and_hash(self, app, client):
        transformation_id = client.post("/api/v1/transformations", json=_valid_transform()).json()[
            "transformation_id"
        ]
        response = client.get(f"/api/v1/transformations/{transformation_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["transformation_id"] == transformation_id
        assert data["version"] == 1
        assert data["logic_definition"]["type"] == "silver"
        assert data["logic_hash"].startswith("sha256:")

    def test_404_unknown(self, app, client):
        response = client.get(f"/api/v1/transformations/{uuid.uuid4()}")
        assert response.status_code == 404


class TestRunTransformation:
    def test_200_run_shape(self, app, client, process_processing_run):
        platform_id = _seed_platform(app)
        bronze_id = _register_dataset(
            app, client, platform_id, name="customer_bronze", layer="bronze"
        )
        silver_id = _register_dataset(app, client, platform_id)
        transformation_id = client.post("/api/v1/transformations", json=_valid_transform()).json()[
            "transformation_id"
        ]

        # Seed Bronze records in the processing gateway.
        app.state.processing_gateway.seed_table(
            bronze_id,
            "bronze",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("email", pa.string()),
                    pa.field("country", pa.string()),
                ]
            ),
            [
                {"customer_id": 1, "email": " a@example.com ", "country": "us"},
                {"customer_id": 2, "email": "b@example.com", "country": "uk"},
            ],
        )

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["output_dataset_id"] == silver_id
        assert data["output_version"] == 1
        assert data["record_count"] == 2
        assert data["quarantined_count"] == 0
        assert data["gate_report_id"] is None
        assert data["promotion_state"] == "silver_validated"

    def test_run_quarantines_duplicates(self, app, client):
        platform_id = _seed_platform(app)
        bronze_id = _register_dataset(
            app, client, platform_id, name="customer_bronze", layer="bronze"
        )
        _register_dataset(app, client, platform_id)
        transformation_id = client.post("/api/v1/transformations", json=_valid_transform()).json()[
            "transformation_id"
        ]

        app.state.processing_gateway.seed_table(
            bronze_id,
            "bronze",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("email", pa.string()),
                ]
            ),
            [
                {"customer_id": 1, "email": "a@example.com"},
                {"customer_id": 1, "email": "a@example.com"},  # duplicate key
            ],
        )

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["record_count"] == 1
        assert data["quarantined_count"] == 1

    def test_run_404_unknown_transformation(self, app, client):
        response = client.post(
            f"/api/v1/transformations/{uuid.uuid4()}/run",
            json={"input_dataset_id": str(uuid.uuid4()), "environment": "production"},
        )
        assert response.status_code == 404


class TestTransformationRuns:
    def test_200_history(self, app, client):
        platform_id = _seed_platform(app)
        bronze_id = _register_dataset(
            app, client, platform_id, name="customer_bronze", layer="bronze"
        )
        _register_dataset(app, client, platform_id)
        transformation_id = client.post("/api/v1/transformations", json=_valid_transform()).json()[
            "transformation_id"
        ]

        app.state.processing_gateway.seed_table(
            bronze_id,
            "bronze",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("email", pa.string()),
                ]
            ),
            [{"customer_id": 1, "email": "a@example.com"}],
        )

        client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        )

        response = client.get(f"/api/v1/transformations/{transformation_id}/runs")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert item["output_version"] == 1
        assert item["record_count"] == 1
        assert item["promotion_state"] == "silver_validated"
        assert item["ran_at"]


def _seed_silver_validated(app, client, platform_id):
    """Register silver + gold datasets and mark silver silver_validated."""
    from datafoundry.controlplane.db.models import PromotionState, PromotionStateRow

    silver_id = _register_dataset(app, client, platform_id, name="customer_silver", layer="silver")
    gold_id = _register_dataset(
        app,
        client,
        platform_id,
        name="customer_gold",
        layer="gold",
        schema_definition={
            "customer_id": {"type": "integer", "nullable": False},
            "total_amount": {"type": "float", "nullable": True},
        },
    )
    with app.state.sessionmaker() as sess:
        sess.add(
            PromotionStateRow(
                dataset_id=uuid.UUID(silver_id), state=PromotionState.silver_validated
            )
        )
        sess.commit()
    return silver_id, gold_id


def _gold_transform(platform_id, **overrides):
    body = {
        "name": "customer_360_gold_transform",
        "source_layer": "silver",
        "target_layer": "gold",
        "reconciliation_tolerance": 5.0,
        "logic": {
            "type": "gold",
            "aggregation": {
                "group_by": ["customer_id"],
                "measures": [{"name": "total_amount", "op": "sum", "column": "amount"}],
            },
        },
    }
    body.update(overrides)
    return body


class TestGoldTransformation:
    def test_reconciliation_pass_promotes(self, app, client):
        platform_id = _seed_platform(app)
        silver_id, gold_id = _seed_silver_validated(app, client, platform_id)
        transformation_id = client.post(
            "/api/v1/transformations", json=_gold_transform(platform_id)
        ).json()["transformation_id"]

        app.state.processing_gateway.seed_table(
            silver_id,
            "silver",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("amount", pa.float64()),
                ]
            ),
            [
                {"customer_id": 1, "amount": 10.0},
                {"customer_id": 1, "amount": 20.0},
                {"customer_id": 2, "amount": 5.0},
            ],
        )

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": silver_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["output_dataset_id"] == gold_id
        assert data["record_count"] == 2
        assert data["promotion_state"] == "gold_validated"

    def test_reconciliation_fail_blocks(self, app, client, make_app):
        platform_id = _seed_platform(app)
        silver_id, gold_id = _seed_silver_validated(app, client, platform_id)
        # Force reconciliation failure on the gold output dataset.
        app.state.processing_gateway.force_reconciliation_fail(gold_id)
        transformation_id = client.post(
            "/api/v1/transformations", json=_gold_transform(platform_id)
        ).json()["transformation_id"]

        app.state.processing_gateway.seed_table(
            silver_id,
            "silver",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("amount", pa.float64()),
                ]
            ),
            [{"customer_id": 1, "amount": 10.0}],
        )

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": silver_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["promotion_state"] == "blocked"

        detail = client.get(f"/api/v1/datasets/{gold_id}").json()
        assert detail["blocked_reason"]
        assert "reconciliation" in detail["blocked_reason"]

    def test_non_silver_validated_input_refused(self, app, client):
        platform_id = _seed_platform(app)
        silver_id = _register_dataset(
            app, client, platform_id, name="customer_silver", layer="silver"
        )
        _register_dataset(
            app, client, platform_id, name="customer_gold", layer="gold", schema_definition={}
        )
        # Silver not validated: leave no promotion row.
        transformation_id = client.post(
            "/api/v1/transformations", json=_gold_transform(platform_id)
        ).json()["transformation_id"]

        app.state.processing_gateway.seed_table(
            silver_id,
            "silver",
            pa.schema([pa.field("amount", pa.float64())]),
            [{"amount": 1.0}],
        )

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": silver_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["promotion_state"] == "blocked"
