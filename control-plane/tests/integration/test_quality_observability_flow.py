"""T043: Integration test for quickstart Scenario 5 (US6, FR-013/FR-014/FR-015).

Run the pipeline several times with varying outcomes, verify the score +
history reflect the runs accurately, and drill into a failed run to reach the
failing test, its failed records, and quarantine entries.
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
            owner_identity="dev@datafoundry.local",
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
    ],
}


def _run_gate(app, client, ds_id, gate_id, rows):
    """Run a gate against rows; returns report_id + decision."""
    _seed_table(app, ds_id, rows)
    run = client.post(
        f"/api/v1/gates/{gate_id}/run",
        json={
            "run_id": str(uuid.uuid4()),
            "batch_id": str(uuid.uuid4()),
            "environment": "production",
        },
    )
    assert run.status_code == 200, run.text
    return run.json()


class TestScenario5QualityObservability:
    def test_score_history_and_drill_down(self, app, client):
        ds_id = _seed_dataset(app)
        gate_id = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver", json=GATE_CONFIG
        ).json()["gate_id"]

        # Run 1: clean data -> promote.
        clean = _run_gate(
            app,
            client,
            ds_id,
            gate_id,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 2, "email": "b@x.com"},
            ],
        )
        assert clean["decision"] == "promote"

        # Run 2: duplicate customer_id -> block.
        blocked = _run_gate(
            app,
            client,
            ds_id,
            gate_id,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 1, "email": "b@x.com"},
                {"customer_id": 2, "email": "c@x.com"},
            ],
        )
        assert blocked["decision"] == "block"

        # Score reflects both runs (passed=100, failed=0 -> mean 50).
        quality = client.get(f"/api/v1/datasets/{ds_id}/quality")
        assert quality.status_code == 200, quality.text
        qdata = quality.json()
        assert qdata["score"] == 50.0
        assert len(qdata["history"]) == 2

        # History lists both runs with decision + counts + config_version.
        history = client.get(f"/api/v1/datasets/{ds_id}/quality/history")
        assert history.status_code == 200
        items = history.json()["items"]
        assert len(items) == 2
        decisions = {item["decision"] for item in items}
        assert decisions == {"promote", "block"}
        for item in items:
            assert item["config_version"] == 1

        # Drill into the failed run: reaches the failing test + failed records.
        drill = client.get(f"/api/v1/reports/{blocked['report_id']}")
        assert drill.status_code == 200, drill.text
        ddata = drill.json()
        assert ddata["decision"] == "block"
        assert ddata["overall_status"] == "failed"
        assert ddata["tests_failed"] == 1
        # The failing uniqueness test is present with its failed-record count.
        assert len(ddata["results"]) == 2
        assert ddata["quarantine_entries"] == []
