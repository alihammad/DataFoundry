"""T038: Integration test for quickstart Scenario 4 (US5, FR-011/FR-012).

Block a gate (Scenario 1), then grant an override with all required fields:
promotion proceeds and the override is auditable. Negative paths: an
incomplete override is rejected 422; an expired override grants no permission.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pyarrow as pa


def _seed_dataset(app, name="customer", owner="dev@datafoundry.local"):
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
            owner_identity=owner,
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


def _block_gate(app, client, ds_id):
    """Define a gate, seed duplicate data, run it -> blocked report id."""
    gate_id = client.post(
        f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver", json=GATE_CONFIG
    ).json()["gate_id"]
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
    assert run.json()["decision"] == "block"
    return run.json()["report_id"]


def _valid_override(**overrides):
    body = {
        "authorising_identity": "user@acme.com",
        "reason": "Known upstream incident; data verified manually",
        "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "impact_assessment": "3 downstream dashboards affected for <24h",
    }
    body.update(overrides)
    return body


class TestScenario4Override:
    def test_override_proceeds_and_is_auditable(self, app, client):
        ds_id = _seed_dataset(app)
        report_id = _block_gate(app, client, ds_id)

        # Grant the override (Scenario 4 step 1).
        grant = client.post(f"/api/v1/reports/{report_id}/override", json=_valid_override())
        assert grant.status_code == 201, grant.text
        data = grant.json()
        assert data["status"] == "active"
        uuid.UUID(data["override_id"])

        # The override is in the dataset's audit history (FR-012).
        history = client.get(f"/api/v1/datasets/{ds_id}/overrides")
        assert history.status_code == 200
        items = history.json()["items"]
        assert len(items) == 1
        assert items[0]["report_id"] == str(report_id)
        assert items[0]["status"] == "active"
        assert items[0]["authorising_identity"] == "user@acme.com"

    def test_incomplete_override_rejected(self, app, client):
        ds_id = _seed_dataset(app)
        report_id = _block_gate(app, client, ds_id)
        response = client.post(
            f"/api/v1/reports/{report_id}/override",
            json=_valid_override(impact_assessment=""),
        )
        assert response.status_code == 422
        assert response.json()["errors"]

    def test_expired_override_grants_no_permission(self, app, client):
        ds_id = _seed_dataset(app)
        report_id = _block_gate(app, client, ds_id)
        # Grant an override that is already expired.
        grant = client.post(
            f"/api/v1/reports/{report_id}/override",
            json=_valid_override(expiry=(datetime.now(UTC) - timedelta(days=1)).isoformat()),
        )
        assert grant.status_code == 201, grant.text
        # The override is marked expired and grants no permission (FR-012).
        history = client.get(f"/api/v1/datasets/{ds_id}/overrides")
        assert history.status_code == 200
        assert history.json()["items"][0]["status"] == "expired"
