"""T029: Integration test for quickstart Scenario 3 (US3, FR-009/FR-010/FR-011).

Define a Gold aggregate over Silver with known totals, run the build, verify
reconciliation + ownership metadata + catalog discoverability; a reconciliation
failure blocks promotion + reports discrepancy; a non-SILVER_VALIDATED input is
refused.
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


def _register_dataset(app, client, platform_id, name, layer, schema):
    body = {
        "platform_id": str(platform_id),
        "name": name,
        "layer": layer,
        "schema_definition": schema,
        "owner_identity": "user@acme.com",
        "classification": "internal",
        "steward_identity": "steward@acme.com",
        "domain": "customer",
        "description": "Customer 360",
        "refresh_metadata": {"schedule": "daily", "freshness_target_minutes": 1440},
        "quality_score": 95,
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _mark_silver_validated(app, silver_id):
    from datafoundry.controlplane.db.models import PromotionState, PromotionStateRow

    with app.state.sessionmaker() as sess:
        sess.add(
            PromotionStateRow(
                dataset_id=uuid.UUID(silver_id), state=PromotionState.silver_validated
            )
        )
        sess.commit()


def _define_gold(client, tolerance=5.0):
    body = {
        "name": "customer_360_gold_transform",
        "source_layer": "silver",
        "target_layer": "gold",
        "reconciliation_tolerance": tolerance,
        "logic": {
            "type": "gold",
            "aggregation": {
                "group_by": ["customer_id"],
                "measures": [{"name": "total_amount", "op": "sum", "column": "amount"}],
            },
        },
    }
    response = client.post("/api/v1/transformations", json=body)
    assert response.status_code == 201, response.text
    return response.json()["transformation_id"]


def _seed_gateway(gateway, silver_id):
    gateway.seed_table(
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


class TestScenario3GoldReconciliation:
    def test_gold_build_with_reconciliation(self, app, client):
        platform_id = _seed_platform(app)
        silver_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "amount": {"type": "float", "nullable": False},
        }
        gold_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "total_amount": {"type": "float", "nullable": True},
        }
        silver_id = _register_dataset(
            app, client, platform_id, "customer_silver", "silver", silver_schema
        )
        gold_id = _register_dataset(app, client, platform_id, "customer_gold", "gold", gold_schema)
        _mark_silver_validated(app, silver_id)
        transformation_id = _define_gold(client)
        _seed_gateway(app.state.processing_gateway, silver_id)

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": silver_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["output_dataset_id"] == gold_id
        assert data["promotion_state"] == "gold_validated"
        assert data["record_count"] == 2

        # Gold data reflects the aggregation.
        from datafoundry.controlplane.db.models import PromotionStateRow

        with app.state.sessionmaker() as sess:
            promo = sess.query(PromotionStateRow).filter_by(dataset_id=uuid.UUID(gold_id)).first()
            assert promo.state.value == "gold_validated"
            assert promo.blocked_reason is None

        table = app.state.processing_gateway.read_table(gold_id, "gold")
        rows = {r["customer_id"]: r["total_amount"] for r in table.to_pylist()}
        assert rows[1] == 30.0
        assert rows[2] == 5.0

        # Catalog discoverability + ownership metadata (FR-014, US3-AC2).
        from datafoundry.controlplane.db.models import CatalogMetadata, LineageLink

        with app.state.sessionmaker() as sess:
            catalog = sess.query(CatalogMetadata).filter_by(dataset_id=uuid.UUID(gold_id)).first()
            assert catalog is not None
            assert catalog.metadata_json["owner"] == "user@acme.com"
            assert catalog.metadata_json["description"] == "Customer 360"
            assert catalog.metadata_json["quality_score"] == 95
            assert catalog.metadata_json["domain"] == "customer"
            lineage = (
                sess.query(LineageLink)
                .filter_by(
                    source_dataset_id=uuid.UUID(silver_id),
                    target_dataset_id=uuid.UUID(gold_id),
                )
                .first()
            )
            assert lineage is not None
            assert lineage.transformation_version == 1

    def test_reconciliation_failure_blocks_and_reports(self, app, client):
        platform_id = _seed_platform(app)
        silver_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "amount": {"type": "float", "nullable": False},
        }
        gold_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "total_amount": {"type": "float", "nullable": True},
        }
        silver_id = _register_dataset(
            app, client, platform_id, "customer_silver", "silver", silver_schema
        )
        gold_id = _register_dataset(app, client, platform_id, "customer_gold", "gold", gold_schema)
        _mark_silver_validated(app, silver_id)
        transformation_id = _define_gold(client, tolerance=0.0)
        _seed_gateway(app.state.processing_gateway, silver_id)

        # Force reconciliation failure (FR-010, US3-AC3).
        app.state.processing_gateway.force_reconciliation_fail(gold_id)

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": silver_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["promotion_state"] == "blocked"
        detail = client.get(f"/api/v1/datasets/{gold_id}").json()
        assert detail["promotion_state"] == "blocked"
        assert "reconciliation" in (detail["blocked_reason"] or "")

    def test_non_silver_validated_input_refused(self, app, client):
        platform_id = _seed_platform(app)
        silver_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "amount": {"type": "float", "nullable": False},
        }
        gold_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "total_amount": {"type": "float", "nullable": True},
        }
        silver_id = _register_dataset(
            app, client, platform_id, "customer_silver", "silver", silver_schema
        )
        gold_id = _register_dataset(app, client, platform_id, "customer_gold", "gold", gold_schema)
        # Silver NOT marked validated.
        transformation_id = _define_gold(client)
        _seed_gateway(app.state.processing_gateway, silver_id)

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": silver_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["promotion_state"] == "blocked"
        detail = client.get(f"/api/v1/datasets/{gold_id}").json()
        assert detail["promotion_state"] == "blocked"
        assert "not silver_validated" in (detail["blocked_reason"] or "")
