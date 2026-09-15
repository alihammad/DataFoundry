"""T034: Integration test for quickstart Scenario 1 env-override (US4, FR-004/FR-005).

The same test is WARNING in Development and CRITICAL in Production. Feed
identical borderline data (duplicate ``customer_id``): the Development run
continues (promote, warning) while the Production run blocks (failed). This
pins the per-environment severity semantics end to end through the API.
"""

from __future__ import annotations

import uuid

import pyarrow as pa


def _seed_dataset(app, name="customer"):
    from datafoundry.controlplane.db.models import (
        DataClassification,
        Dataset,
        DatasetLayer,
    )

    with app.state.sessionmaker() as sess:
        ds = Dataset(
            name=name,
            layer=DatasetLayer.silver,
            schema_definition={"customer_id": {"type": "integer", "nullable": False}},
            owner_identity="user@acme.com",
            classification=DataClassification.internal,
        )
        sess.add(ds)
        sess.commit()
        return ds.id


def _seed_table(app, dataset_id, rows):
    schema = pa.schema([pa.field("customer_id", pa.int64()), pa.field("email", pa.string())])
    app.state.quality_gateway.seed_table(str(dataset_id), "silver", schema, rows)


# Same test: WARNING by default, escalated to CRITICAL only in Production.
GATE_CONFIG = {
    "transition": "bronze_to_silver",
    "environment_overrides": {
        "production": {"uniqueness_customer_id": "critical"},
    },
    "tests": [
        {
            "name": "uniqueness_customer_id",
            "category": "uniqueness",
            "severity": "warning",
            "parameters": {"columns": ["customer_id"]},
        },
        {
            "name": "nullability_email",
            "category": "nullability",
            "severity": "critical",
            "parameters": {"columns": ["email"]},
        },
    ],
}


class TestScenario1EnvOverride:
    def test_development_continues_production_blocks(self, app, client):
        ds_id = _seed_dataset(app)
        define = client.post(f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver", json=GATE_CONFIG)
        assert define.status_code == 201, define.text
        gate_id = define.json()["gate_id"]

        # Identical borderline data: duplicate customer_id values.
        _seed_table(
            app,
            ds_id,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 1, "email": "b@x.com"},
                {"customer_id": 2, "email": "c@x.com"},
            ],
        )

        # Development: uniqueness is WARNING -> continues (promote, warning).
        dev = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "development",
            },
        )
        assert dev.status_code == 200, dev.text
        dev_data = dev.json()
        assert dev_data["decision"] == "promote"
        assert dev_data["overall_status"] == "warning"
        assert dev_data["tests_failed"] == 1
        assert dev_data["tests_warned"] == 0

        # Production: uniqueness escalated to CRITICAL -> blocks (failed).
        prod = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        )
        assert prod.status_code == 200, prod.text
        prod_data = prod.json()
        assert prod_data["decision"] == "block"
        assert prod_data["overall_status"] == "failed"
        assert prod_data["tests_failed"] == 1

        # The failing test is the same in both runs; only the effective
        # severity differs by environment.
        dev_uniqueness = next(
            r for r in dev_data["results"] if r["test"] == "uniqueness_customer_id"
        )
        prod_uniqueness = next(
            r for r in prod_data["results"] if r["test"] == "uniqueness_customer_id"
        )
        assert dev_uniqueness["status"] == "failed"
        assert prod_uniqueness["status"] == "failed"
        assert dev_uniqueness["failed_record_count"] == 1
        assert prod_uniqueness["failed_record_count"] == 1
