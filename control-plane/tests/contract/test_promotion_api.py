"""T034: Contract tests for the promotion API (processing-api.md §3).

Covers:
- GET /datasets/{id}/promotion: current state + history with gate_report_id +
  transitioned_at + blocked_reason.
- POST /datasets/{id}/promotion/override: 201 active; 422 incomplete; 403
  unauthorised + recorded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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


def _register_dataset(app, client, platform_id, owner="dev@datafoundry.local"):
    body = {
        "platform_id": str(platform_id),
        "name": "customer_silver",
        "layer": "silver",
        "schema_definition": {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        },
        "owner_identity": owner,
        "classification": "internal",
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _seed_blocked(app, dataset_id, gate_report_id=None):
    from datafoundry.controlplane.db.models import PromotionState, PromotionStateRow

    with app.state.sessionmaker() as sess:
        sess.add(
            PromotionStateRow(
                dataset_id=uuid.UUID(dataset_id),
                state=PromotionState.blocked,
                gate_report_id=gate_report_id,
                blocked_reason="gate failed for customer_silver",
            )
        )
        sess.commit()


def _seed_report(app, dataset_id):
    from datafoundry.controlplane.db.models import (
        GateDecision,
        GateReport,
        LayerTransition,
        OverallStatus,
        QualityGate,
    )

    with app.state.sessionmaker() as sess:
        gate = QualityGate(
            dataset_id=uuid.UUID(dataset_id),
            transition=LayerTransition.bronze_to_silver,
            config_version=1,
            config_yaml="{}",
            config_hash="a" * 64,
            created_by="dev@datafoundry.local",
        )
        sess.add(gate)
        sess.flush()
        report = GateReport(
            gate_id=gate.id,
            dataset_id=uuid.UUID(dataset_id),
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


class TestGetPromotion:
    def test_200_with_state_and_history(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        _seed_blocked(app, dataset_id)

        response = client.get(f"/api/v1/datasets/{dataset_id}/promotion")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["dataset_id"] == dataset_id
        assert data["current_state"] == "blocked"
        assert len(data["history"]) == 1
        item = data["history"][0]
        assert item["state"] == "blocked"
        assert item["blocked_reason"] == "gate failed for customer_silver"
        assert item["transitioned_at"]

    def test_200_unregistered(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        response = client.get(f"/api/v1/datasets/{dataset_id}/promotion")
        assert response.status_code == 200
        data = response.json()
        assert data["current_state"] is None
        assert data["history"] == []

    def test_404_unknown(self, app, client):
        response = client.get(f"/api/v1/datasets/{uuid.uuid4()}/promotion")
        assert response.status_code == 404


class TestOverrideBlockedGate:
    def _valid_override(self, **overrides):
        body = {
            "authorising_identity": "dev@datafoundry.local",
            "reason": "Known upstream incident; data verified manually",
            "expiry": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
            "impact_assessment": "3 downstream dashboards affected for <24h",
        }
        body.update(overrides)
        return body

    def test_201_active(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        report_id = _seed_report(app, dataset_id)
        _seed_blocked(app, dataset_id, gate_report_id=report_id)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/promotion/override",
            json=self._valid_override(),
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["status"] == "active"
        uuid.UUID(data["override_id"])

    def test_audit_written(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        report_id = _seed_report(app, dataset_id)
        _seed_blocked(app, dataset_id, gate_report_id=report_id)
        assert (
            client.post(
                f"/api/v1/datasets/{dataset_id}/promotion/override",
                json=self._valid_override(),
            ).status_code
            == 201
        )
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "promotion.overridden" in actions

    def test_422_incomplete(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        report_id = _seed_report(app, dataset_id)
        _seed_blocked(app, dataset_id, gate_report_id=report_id)

        body = self._valid_override()
        del body["reason"]
        response = client.post(f"/api/v1/datasets/{dataset_id}/promotion/override", json=body)
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_403_unauthorised_recorded(self, app, client, session_factory):

        platform_id = _seed_platform(app)
        # Dataset owned by someone else; caller is dev@datafoundry.local.
        dataset_id = _register_dataset(app, client, platform_id, owner="other@acme.com")
        report_id = _seed_report(app, dataset_id)
        _seed_blocked(app, dataset_id, gate_report_id=report_id)

        response = client.post(
            f"/api/v1/datasets/{dataset_id}/promotion/override",
            json=self._valid_override(),
        )
        assert response.status_code == 403
        assert response.json()["code"] == "insufficient_permissions"

    def test_404_no_blocked_report(self, app, client):
        platform_id = _seed_platform(app)
        dataset_id = _register_dataset(app, client, platform_id)
        response = client.post(
            f"/api/v1/datasets/{dataset_id}/promotion/override",
            json=self._valid_override(),
        )
        assert response.status_code == 404
