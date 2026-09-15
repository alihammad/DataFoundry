"""T021: Contract tests for the contracts API (contracts/quality-api.md §3).

Covers:
- POST /datasets/{id}/contracts/register: 201 explicit approved; 422 invalid
  schema.
- POST /datasets/{id}/contracts/infer: 201 pending (never auto-approved).
- POST /contracts/{id}/approve: 200 approved; owner authorisation (403).
- GET /datasets/{id}/contracts: list + violations.
"""

from __future__ import annotations

import uuid

PROBLEM_CT = "application/problem+json"

VALID_SCHEMA = {
    "customer_id": {"type": "integer", "nullable": False},
    "email": {"type": "string", "nullable": False},
}


def _seed_dataset(app, name="customer", owner="user@acme.com"):
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


class TestRegisterContract:
    def test_register_explicit_approved(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/register",
            json={"schema_definition": VALID_SCHEMA},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"contract_id", "version", "origin", "approval_status"}
        assert data["version"] == 1
        assert data["origin"] == "explicit"
        assert data["approval_status"] == "approved"
        uuid.UUID(data["contract_id"])

    def test_register_increments_version(self, app, client):
        ds_id = _seed_dataset(app)
        for _ in range(2):
            response = client.post(
                f"/api/v1/datasets/{ds_id}/contracts/register",
                json={"schema_definition": VALID_SCHEMA},
            )
            assert response.status_code == 201
        assert response.json()["version"] == 2

    def test_register_invalid_schema_422(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/register",
            json={"schema_definition": {"bad": {"type": "not_a_type", "nullable": False}}},
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_register_empty_schema_422(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/register",
            json={"schema_definition": {}},
        )
        assert response.status_code == 422

    def test_register_unknown_dataset_404(self, app, client):
        response = client.post(
            f"/api/v1/datasets/{uuid.uuid4()}/contracts/register",
            json={"schema_definition": VALID_SCHEMA},
        )
        assert response.status_code == 404


class TestInferContract:
    def test_infer_pending(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/infer",
            json={"schema_definition": VALID_SCHEMA},
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["origin"] == "inferred"
        assert data["approval_status"] == "pending"
        assert data["version"] == 1

    def test_infer_never_auto_approved(self, app, client):
        """Inferred contracts are never auto-approved (constitution V, FR-007)."""
        ds_id = _seed_dataset(app)
        data = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/infer",
            json={"schema_definition": VALID_SCHEMA},
        ).json()
        assert data["approval_status"] == "pending"


class TestApproveContract:
    def test_owner_approves(self, app, client):
        # dev identity is dev@datafoundry.local (settings.dev_identity).
        ds_id = _seed_dataset(app, owner="dev@datafoundry.local")
        contract_id = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/infer",
            json={"schema_definition": VALID_SCHEMA},
        ).json()["contract_id"]
        response = client.post(f"/api/v1/contracts/{contract_id}/approve", json={})
        assert response.status_code == 200, response.text
        assert response.json()["approval_status"] == "approved"

    def test_owner_rejects(self, app, client):
        ds_id = _seed_dataset(app, owner="dev@datafoundry.local")
        contract_id = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/infer",
            json={"schema_definition": VALID_SCHEMA},
        ).json()["contract_id"]
        response = client.post(
            f"/api/v1/contracts/{contract_id}/approve", json={"action": "reject"}
        )
        assert response.status_code == 200
        assert response.json()["approval_status"] == "rejected"

    def test_non_owner_forbidden(self, app, client):
        """Only the dataset owner may approve (US2-AC4)."""
        ds_id = _seed_dataset(app, owner="owner@acme.com")
        contract_id = client.post(
            f"/api/v1/datasets/{ds_id}/contracts/infer",
            json={"schema_definition": VALID_SCHEMA},
        ).json()["contract_id"]
        # dev identity is dev@datafoundry.local, not the owner.
        response = client.post(f"/api/v1/contracts/{contract_id}/approve", json={})
        assert response.status_code == 403
        assert response.headers["content-type"].startswith(PROBLEM_CT)

    def test_approve_unknown_contract_404(self, app, client):
        response = client.post(f"/api/v1/contracts/{uuid.uuid4()}/approve", json={})
        assert response.status_code == 404


class TestListContracts:
    def test_list_contracts_with_violations(self, app, client):
        ds_id = _seed_dataset(app)
        client.post(
            f"/api/v1/datasets/{ds_id}/contracts/register",
            json={"schema_definition": VALID_SCHEMA},
        )
        response = client.get(f"/api/v1/datasets/{ds_id}/contracts")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert item["origin"] == "explicit"
        assert item["approval_status"] == "approved"
        assert "violations" in item

    def test_list_contracts_empty(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.get(f"/api/v1/datasets/{ds_id}/contracts")
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_list_contracts_unknown_dataset_404(self, app, client):
        response = client.get(f"/api/v1/datasets/{uuid.uuid4()}/contracts")
        assert response.status_code == 404
