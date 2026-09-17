"""T031: Contract tests for the source-contracts API (ingestion-api.md §5).

Covers:
- GET /api/v1/sources/{id}/contracts: 200 {items:[{contract_id, object_name,
  origin, approval_status}]}; 404 for unknown source.
- POST /api/v1/contracts/{id}/approve: 200 {approval_status:"approved"};
  owner authorisation (403 for non-owner); audit written; 404 unknown.
"""

from __future__ import annotations

import uuid

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


def _register_source(app, client, *, owner="dev@datafoundry.local"):
    platform_id = _seed_platform(app)
    body = {
        "platform_id": str(platform_id),
        "name": "crm-prod",
        "type": "postgres",
        "config": {
            "host": "crm.internal",
            "port": 5432,
            "database": "crm",
            "credentials": {"secretRef": "crm-ro-user"},
        },
    }
    response = client.post("/api/v1/sources", json=body)
    assert response.status_code == 201, response.text
    source_id = response.json()["source_id"]
    # The dev caller is dev@datafoundry.local; override owner if needed.
    if owner != "dev@datafoundry.local":
        from datafoundry.controlplane.db.models import DataSource

        with app.state.sessionmaker() as sess:
            src = sess.get(DataSource, uuid.UUID(source_id))
            src.owner_identity = owner
            sess.commit()
    return source_id


def _seed_source_contract(app, source_id, *, object_name="customer"):
    from datafoundry.controlplane.db.models import (
        ApprovalStatus,
        ContractOrigin,
        SourceContract,
    )

    with app.state.sessionmaker() as sess:
        contract = SourceContract(
            source_id=uuid.UUID(source_id),
            object_name=object_name,
            schema_definition={
                "customer_id": {"type": "integer", "nullable": False},
                "email": {"type": "string", "nullable": False},
            },
            origin=ContractOrigin.inferred,
            approval_status=ApprovalStatus.pending,
            created_by="dev@datafoundry.local",
        )
        sess.add(contract)
        sess.commit()
        return contract.id


class TestListSourceContracts:
    def test_200_shape(self, app, client):
        source_id = _register_source(app, client)
        contract_id = _seed_source_contract(app, source_id)

        response = client.get(f"/api/v1/sources/{source_id}/contracts")
        assert response.status_code == 200, response.text
        data = response.json()
        assert set(data) == {"items"}
        item = data["items"][0]
        assert set(item) == {"contract_id", "object_name", "origin", "approval_status"}
        assert item["contract_id"] == str(contract_id)
        assert item["object_name"] == "customer"
        assert item["origin"] == "inferred"
        assert item["approval_status"] == "pending"

    def test_404_unknown_source(self, app, client):
        response = client.get(f"/api/v1/sources/{uuid.uuid4()}/contracts")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_CT)


class TestApproveSourceContract:
    def test_200_approved(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        source_id = _register_source(app, client)
        contract_id = _seed_source_contract(app, source_id)

        response = client.post(f"/api/v1/contracts/{contract_id}/approve", json={})
        assert response.status_code == 200, response.text
        assert response.json() == {"approval_status": "approved"}

        # Audit written.
        with session_factory() as sess:
            actions = [r.action for r in sess.query(AuditRecord).all()]
        assert "source_contract.approved" in actions

    def test_403_non_owner(self, app, client):
        source_id = _register_source(app, client, owner="other@datafoundry.local")
        contract_id = _seed_source_contract(app, source_id)

        response = client.post(f"/api/v1/contracts/{contract_id}/approve", json={})
        assert response.status_code == 403
        assert response.headers["content-type"].startswith(PROBLEM_CT)

    def test_404_unknown_contract(self, app, client):
        response = client.post(f"/api/v1/contracts/{uuid.uuid4()}/approve", json={})
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_CT)
