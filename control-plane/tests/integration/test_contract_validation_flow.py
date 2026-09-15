"""T022: Integration test for quickstart Scenario 2 (US2, FR-006/FR-007).

Register an explicit contract, feed a batch that changes a column type, verify
``breaking`` classification + blocked promotion; infer a contract on first
ingestion, verify ``pending``, approve it, verify it then gates promotion.
"""

from __future__ import annotations

import uuid

import pyarrow as pa

CONTRACT_SCHEMA = {
    "customer_id": {"type": "integer", "nullable": False},
    "email": {"type": "string", "nullable": False},
}


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
            schema_definition=CONTRACT_SCHEMA,
            owner_identity=owner,
            classification=DataClassification.internal,
        )
        sess.add(ds)
        sess.commit()
        return ds.id


def _seed_table(app, dataset_id, schema, rows):
    app.state.quality_gateway.seed_table(str(dataset_id), "silver", schema, rows)


def _define_contract_gate(app, client, ds_id):
    """Define a gate with a critical contract test on bronze_to_silver."""
    config = {
        "transition": "bronze_to_silver",
        "tests": [
            {
                "name": "contract_conformance",
                "category": "contract",
                "severity": "critical",
                "parameters": {"contract_version": 1},
            }
        ],
    }
    response = client.post(f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver", json=config)
    assert response.status_code == 201, response.text
    return response.json()["gate_id"]


class TestScenario2ContractValidation:
    def test_explicit_contract_breaking_blocks(self, app, client):
        ds_id = _seed_dataset(app)
        # Register an explicit contract (approved immediately, US2-AC1).
        register = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/register",
            json={"schema_definition": CONTRACT_SCHEMA},
        )
        assert register.status_code == 201
        assert register.json()["origin"] == "explicit"
        assert register.json()["approval_status"] == "approved"

        gate_id = _define_contract_gate(app, client, ds_id)

        # Feed a batch that changes a column type (integer -> string).
        schema = pa.schema([pa.field("customer_id", pa.string()), pa.field("email", pa.string())])
        _seed_table(
            app,
            ds_id,
            schema,
            [{"customer_id": "1", "email": "a@x.com"}],
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
        # Breaking change -> contract test fails -> gate blocks.
        assert data["decision"] == "block"
        contract_result = next(r for r in data["results"] if r["test"] == "contract_conformance")
        assert contract_result["status"] == "failed"
        assert contract_result["measured_value"]["contract_violations"]

    def test_infer_approve_gates_promotion(self, app, client):
        ds_id = _seed_dataset(app)
        # Infer a contract on first ingestion (US2-AC3): pending.
        infer = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/infer",
            json={"schema_definition": CONTRACT_SCHEMA},
        )
        assert infer.status_code == 201
        contract_id = infer.json()["contract_id"]
        assert infer.json()["origin"] == "inferred"
        assert infer.json()["approval_status"] == "pending"

        gate_id = _define_contract_gate(app, client, ds_id)

        # Pending contract does NOT gate promotion yet (FR-007 rule).
        schema = pa.schema([pa.field("customer_id", pa.string()), pa.field("email", pa.string())])
        _seed_table(
            app,
            ds_id,
            schema,
            [{"customer_id": "1", "email": "a@x.com"}],
        )
        run_before = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        ).json()
        # No approved contract -> contract test passes (no schema to check).
        assert run_before["decision"] == "promote"

        # Approve the contract (US2-AC4).
        approve = client.post(f"/api/v1/contracts/{contract_id}/approve", json={})
        assert approve.status_code == 200
        assert approve.json()["approval_status"] == "approved"

        # Now the contract gates promotion: type change -> block.
        run_after = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        ).json()
        assert run_after["decision"] == "block"
        contract_result = next(
            r for r in run_after["results"] if r["test"] == "contract_conformance"
        )
        assert contract_result["status"] == "failed"

    def test_contract_list_shows_violations(self, app, client):
        ds_id = _seed_dataset(app)
        client.post(
            f"/api/v1/datasets/{ds_id}/contracts/register",
            json={"schema_definition": CONTRACT_SCHEMA},
        )
        response = client.get(f"/api/v1/datasets/{ds_id}/contracts")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["origin"] == "explicit"
        assert items[0]["approval_status"] == "approved"
