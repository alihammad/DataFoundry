"""T037: Contract tests for the overrides API (contracts/quality-api.md §5).

Covers:
- POST /reports/{id}/override: 201 active; 422 incomplete; 403 unauthorised
  (attempt recorded, US5-AC2).
- GET /datasets/{id}/overrides: audit history (FR-012).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

PROBLEM_CT = "application/problem+json"


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


def _seed_blocked_report(app, ds_id):
    """Create a QualityGate + a blocked GateReport for a dataset."""
    from datafoundry.controlplane.db.models import (
        GateDecision,
        GateReport,
        LayerTransition,
        OverallStatus,
        QualityGate,
    )

    with app.state.sessionmaker() as sess:
        gate = QualityGate(
            dataset_id=ds_id,
            transition=LayerTransition.bronze_to_silver,
            config_version=1,
            config_yaml="transition: bronze_to_silver",
            config_hash="a" * 64,
            environment_overrides={},
            created_by="user@acme.com",
        )
        sess.add(gate)
        sess.flush()
        report = GateReport(
            gate_id=gate.id,
            dataset_id=ds_id,
            run_id=uuid.uuid4(),
            config_version=1,
            decision=GateDecision.block,
            overall_status=OverallStatus.failed,
            tests_run=1,
            tests_passed=0,
            tests_warned=0,
            tests_failed=1,
        )
        sess.add(report)
        sess.commit()
        return report.id


def _valid_override(**overrides):
    body = {
        "authorising_identity": "user@acme.com",
        "reason": "Known upstream incident; data verified manually",
        "expiry": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "impact_assessment": "3 downstream dashboards affected for <24h",
    }
    body.update(overrides)
    return body


class TestGrantOverride:
    def test_grant_override_201(self, app, client):
        ds_id = _seed_dataset(app)
        report_id = _seed_blocked_report(app, ds_id)
        response = client.post(f"/api/v1/reports/{report_id}/override", json=_valid_override())
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"override_id", "status"}
        uuid.UUID(data["override_id"])
        assert data["status"] == "active"

    def test_incomplete_override_422(self, app, client):
        ds_id = _seed_dataset(app)
        report_id = _seed_blocked_report(app, ds_id)
        response = client.post(
            f"/api/v1/reports/{report_id}/override",
            json=_valid_override(reason=""),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_unauthorised_403(self, app, client):
        ds_id = _seed_dataset(app, owner="owner@acme.com")
        report_id = _seed_blocked_report(app, ds_id)
        # Caller is dev@datafoundry.local (settings.dev_identity), not the owner.
        response = client.post(f"/api/v1/reports/{report_id}/override", json=_valid_override())
        assert response.status_code == 403
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["code"] == "insufficient_permissions"

    def test_unknown_report_404(self, app, client):
        response = client.post(f"/api/v1/reports/{uuid.uuid4()}/override", json=_valid_override())
        assert response.status_code == 404


class TestListOverrides:
    def test_list_overrides(self, app, client):
        ds_id = _seed_dataset(app)
        report_id = _seed_blocked_report(app, ds_id)
        client.post(f"/api/v1/reports/{report_id}/override", json=_valid_override())
        response = client.get(f"/api/v1/datasets/{ds_id}/overrides")
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert set(item) == {
            "override_id",
            "report_id",
            "authorising_identity",
            "reason",
            "expiry",
            "status",
            "granted_at",
        }
        uuid.UUID(item["override_id"])
        assert item["report_id"] == str(report_id)
        assert item["authorising_identity"] == "user@acme.com"
        assert item["status"] == "active"

    def test_list_empty(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.get(f"/api/v1/datasets/{ds_id}/overrides")
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_list_unknown_dataset_404(self, app, client):
        response = client.get(f"/api/v1/datasets/{uuid.uuid4()}/overrides")
        assert response.status_code == 404
