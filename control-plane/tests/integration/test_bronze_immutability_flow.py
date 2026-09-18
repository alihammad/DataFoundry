"""T015: Integration test for quickstart Scenario 1 (US1, FR-002/FR-003/FR-004).

Register a Bronze dataset from an ingested batch, verify full batch metadata
(FR-004), verify an immutability-violation attempt is rejected + recorded
(FR-002), and replay Bronze into a fresh Silver run without source access
(FR-003).
"""

from __future__ import annotations

import uuid

import pyarrow as pa
import pytest


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


def _register_dataset(app, client, platform_id, name="customer_bronze", layer="bronze"):
    body = {
        "platform_id": str(platform_id),
        "name": name,
        "layer": layer,
        "schema_definition": {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        },
        "owner_identity": "user@acme.com",
        "classification": "internal",
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _define_transformation(app, name="customer_silver_transform"):
    """Persist a silver transformation directly (transformations API is Phase 4)."""
    from datafoundry.controlplane.db.models import DatasetLayer, Transformation

    with app.state.sessionmaker() as sess:
        transformation = Transformation(
            name=name,
            version=1,
            source_layer=DatasetLayer.bronze,
            target_layer=DatasetLayer.silver,
            logic_definition={
                "type": "silver",
                "cleansing": [{"column": "email", "op": "trim"}],
                "standardisation": [],
                "schema_enforcement": {
                    "customer_id": {"type": "integer", "nullable": False},
                    "email": {"type": "string", "nullable": False},
                },
            },
            logic_hash="a" * 64,
            dedup_keys=["customer_id"],
            owner_identity="user@acme.com",
        )
        sess.add(transformation)
        sess.commit()
        return transformation.id


class TestScenario1BronzeImmutability:
    def test_register_immutability_replay(self, app, client, process_processing_run):
        platform_id = _seed_platform(app)
        bronze_id = _register_dataset(app, client, platform_id)

        # Register Bronze from an ingested batch (FR-004): attach batch metadata.
        from datafoundry.controlplane.processing.engine import register_bronze_dataset

        with app.state.sessionmaker() as sess:
            register_bronze_dataset(
                sess,
                gateway=app.state.processing_gateway,
                dataset_id=uuid.UUID(bronze_id),
                batch_metadata={
                    "source_system": "crm-prod",
                    "source_object": "customer",
                    "ingestion_timestamp": "2026-09-18T00:00:00Z",
                    "batch_id": "batch-1",
                    "pipeline_id": "pipeline-1",
                    "record_count": 2,
                    "ingestion_status": "ingestion_validated",
                },
            )
            sess.commit()

        # Seed Bronze records in the processing gateway (after registration so
        # the empty registration snapshot does not clear them).
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
                {"customer_id": 2, "email": "b@example.com"},
            ],
        )

        # Verify batch metadata on the dataset's version.
        from datafoundry.controlplane.db.models import DatasetVersion

        with app.state.sessionmaker() as sess:
            version = sess.query(DatasetVersion).filter_by(dataset_id=uuid.UUID(bronze_id)).first()
            assert version.input_versions["batch"]["source_system"] == "crm-prod"
            assert version.input_versions["batch"]["record_count"] == 2

        # Immutability violation: attempt to modify Bronze -> rejected + recorded.
        from datafoundry.controlplane.processing.engine import (
            BronzeImmutabilityError,
            enforce_bronze_immutability,
        )

        with app.state.sessionmaker() as sess:
            try:
                enforce_bronze_immutability(
                    sess,
                    gateway=app.state.processing_gateway,
                    dataset_id=uuid.UUID(bronze_id),
                    operation="delete-records",
                )
                pytest.fail("expected BronzeImmutabilityError")
            except BronzeImmutabilityError:
                pass
            sess.commit()

        from datafoundry.controlplane.db.models import PromotionStateRow

        with app.state.sessionmaker() as sess:
            promo = sess.query(PromotionStateRow).filter_by(dataset_id=uuid.UUID(bronze_id)).first()
            assert promo.state.value == "blocked"
            assert "immutability violation" in promo.blocked_reason

        # Replay Bronze into a fresh Silver run without source access.
        # Define a silver transformation + silver dataset.
        silver_id = _register_dataset(
            app, client, platform_id, name="customer_silver", layer="silver"
        )
        transformation_id = _define_transformation(app)

        result = process_processing_run(transformation_id, uuid.UUID(bronze_id))
        assert result["output_dataset_id"] == silver_id
        assert result["record_count"] == 2
        assert result["promotion_state"] in ("silver", "silver_validated", "blocked")

        # Silver records reflect Bronze (no source access).
        table = app.state.processing_gateway.read_table(silver_id, "silver")
        assert table.num_rows == 2
