"""T022: Integration test for quickstart Scenario 2 (US2, FR-005/FR-006).

Define a Silver transform, run it over a Bronze dataset with known
duplicates/type-errors/nulls, verify clean records in Silver + bad records
quarantined with reasons + quality results recorded + dedup per keys + version
traceability.
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
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _define_transform(client, **overrides):
    body = {
        "name": "customer_silver_transform",
        "source_layer": "bronze",
        "target_layer": "silver",
        "dedup_keys": ["customer_id"],
        "reconciliation_tolerance": 0.5,
        "logic": {
            "type": "silver",
            "cleansing": [
                {"column": "email", "op": "trim"},
                {"column": "age", "op": "coerce_type", "to": "integer"},
            ],
            "standardisation": [{"column": "country", "op": "upper"}],
            "schema_enforcement": {
                "customer_id": {"type": "integer", "nullable": False},
                "email": {"type": "string", "nullable": False},
                "age": {"type": "integer", "nullable": True},
                "country": {"type": "string", "nullable": True},
            },
        },
    }
    body.update(overrides)
    response = client.post("/api/v1/transformations", json=body)
    assert response.status_code == 201, response.text
    return response.json()["transformation_id"]


class TestScenario2SilverTransformation:
    def test_clean_dedup_quarantine_version_traceability(self, app, client):
        platform_id = _seed_platform(app)
        bronze_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
            "age": {"type": "string", "nullable": True},
            "country": {"type": "string", "nullable": True},
        }
        bronze_id = _register_dataset(
            app, client, platform_id, "customer_bronze", "bronze", bronze_schema
        )
        silver_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
            "age": {"type": "integer", "nullable": True},
            "country": {"type": "string", "nullable": True},
        }
        silver_id = _register_dataset(
            app, client, platform_id, "customer_silver", "silver", silver_schema
        )
        transformation_id = _define_transform(client)

        # Bronze records: duplicates, type errors, nulls.
        app.state.processing_gateway.seed_table(
            bronze_id,
            "bronze",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("email", pa.string()),
                    pa.field("age", pa.string()),
                    pa.field("country", pa.string()),
                ]
            ),
            [
                {"customer_id": 1, "email": " a@example.com ", "age": "30", "country": "us"},
                {"customer_id": 1, "email": " a@example.com ", "age": "30", "country": "us"},
                {
                    "customer_id": 2,
                    "email": "b@example.com",
                    "age": "not-a-number",
                    "country": "uk",
                },
                {"customer_id": 3, "email": "c@example.com", "age": None, "country": None},
            ],
        )

        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["output_dataset_id"] == silver_id
        # 4 input rows: 1 duplicate + 1 type-error quarantined -> 2 clean.
        assert data["record_count"] == 2
        assert data["quarantined_count"] == 2
        assert data["promotion_state"] == "silver_validated"

        # Clean records in Silver: dedup per business key (US2-AC3), trimmed,
        # standardised, type-converted.
        table = app.state.processing_gateway.read_table(silver_id, "silver")
        assert table.num_rows == 2
        rows = table.to_pylist()
        by_id = {r["customer_id"]: r for r in rows}
        assert by_id[1]["email"] == "a@example.com"  # trimmed
        assert by_id[1]["age"] == 30  # coerced to integer
        assert by_id[1]["country"] == "US"  # standardised upper
        assert by_id[3]["age"] is None  # null preserved

        # Bad records quarantined with reasons (FR-006).
        from datafoundry.controlplane.db.models import DatasetVersion

        with app.state.sessionmaker() as sess:
            version = (
                sess.query(DatasetVersion)
                .filter_by(dataset_id=uuid.UUID(silver_id))
                .order_by(DatasetVersion.version.desc())
                .first()
            )
            assert version.record_count == 2
            assert version.quarantined_count == 2
            assert version.transformation_id == uuid.UUID(transformation_id)

        # Version traceability: prior runs traceable to producing version.
        runs = client.get(f"/api/v1/transformations/{transformation_id}/runs").json()["items"]
        assert len(runs) == 1
        assert runs[0]["output_version"] == 1
        assert runs[0]["record_count"] == 2
        assert runs[0]["quarantined_count"] == 2

        # Reprocessing the same source deduplicates: no new clean rows.
        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        )
        assert response.status_code == 200
        assert response.json()["record_count"] == 2
        assert response.json()["output_version"] == 2
        runs = client.get(f"/api/v1/transformations/{transformation_id}/runs").json()["items"]
        assert len(runs) == 2
        assert runs[0]["output_version"] == 2  # newest first
        assert runs[1]["output_version"] == 1
