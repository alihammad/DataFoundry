"""T015: Integration test for quickstart Scenario 1 (US1, FR-001/FR-002).

Define a Bronze->Silver gate with a critical uniqueness test, run it against a
batch with duplicate ``customer_id`` values, verify ``decision: block``,
promotion does not occur, and the report lists the failing test + failed-record
count.
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


GATE_CONFIG = {
    "transition": "bronze_to_silver",
    "tests": [
        {
            "name": "uniqueness_customer_id",
            "category": "uniqueness",
            "severity": "critical",
            "parameters": {"columns": ["customer_id"]},
        },
        {
            "name": "nullability_email",
            "category": "nullability",
            "severity": "error",
            "parameters": {"columns": ["email"]},
        },
        {
            "name": "freshness_check",
            "category": "freshness",
            "severity": "warning",
            "parameters": {"max_staleness_minutes": 30},
        },
        {
            "name": "volume_check",
            "category": "volume",
            "severity": "critical",
            "parameters": {"min_records": 1},
        },
    ],
}


class TestScenario1GateBlocksBadData:
    def test_gate_blocks_duplicate_batch(self, app, client):
        ds_id = _seed_dataset(app)
        # Define the gate (Scenario 1 step 1).
        define = client.post(f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver", json=GATE_CONFIG)
        assert define.status_code == 201, define.text
        gate_id = define.json()["gate_id"]
        assert define.json()["config_version"] == 1

        # Seed a batch with duplicate customer_id values (Scenario 1 step 2).
        _seed_table(
            app,
            ds_id,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 1, "email": "b@x.com"},
                {"customer_id": 2, "email": "c@x.com"},
            ],
        )
        run = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        )
        assert run.status_code == 200, run.text
        data = run.json()

        # Expected 1: decision block, overall failed, tests_failed 1.
        assert data["decision"] == "block"
        assert data["overall_status"] == "failed"
        assert data["tests_failed"] == 1
        assert data["tests_run"] == 4

        # Expected 3: report lists every test with pass/fail/warning status and
        # the failed-record count (US1-AC3).
        report = client.get(f"/api/v1/gates/{gate_id}/reports/{data['report_id']}")
        assert report.status_code == 200
        report_data = report.json()
        by_name = {item["test"]: item for item in report_data["results"]}
        assert set(by_name) == {
            "uniqueness_customer_id",
            "nullability_email",
            "freshness_check",
            "volume_check",
        }
        uniqueness = by_name["uniqueness_customer_id"]
        assert uniqueness["status"] == "failed"
        assert uniqueness["failed_record_count"] == 1
        assert uniqueness["measured_value"]["duplicates"] == 1
        # The other tests pass (no nulls, fresh, volume met).
        assert by_name["nullability_email"]["status"] == "passed"
        assert by_name["freshness_check"]["status"] == "passed"
        assert by_name["volume_check"]["status"] == "passed"

    def test_gate_without_critical_test_rejected(self, app, client):
        """A gate with no CRITICAL/ERROR test is rejected 422 (fail-closed)."""
        ds_id = _seed_dataset(app)
        bad_config = {
            "transition": "bronze_to_silver",
            "tests": [
                {
                    "name": "only_warning",
                    "category": "uniqueness",
                    "severity": "warning",
                    "parameters": {"columns": ["customer_id"]},
                }
            ],
        }
        response = client.post(f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver", json=bad_config)
        assert response.status_code == 422

    def test_promote_on_clean_batch(self, app, client):
        """A clean batch promotes (no CRITICAL/ERROR failure)."""
        ds_id = _seed_dataset(app)
        gate_id = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver", json=GATE_CONFIG
        ).json()["gate_id"]
        _seed_table(
            app,
            ds_id,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 2, "email": "b@x.com"},
            ],
        )
        run = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        ).json()
        assert run["decision"] == "promote"
        assert run["overall_status"] == "passed"
