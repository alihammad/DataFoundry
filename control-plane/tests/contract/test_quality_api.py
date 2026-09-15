"""T042: Contract tests for the quality API (contracts/quality-api.md §6).

Covers:
- GET /datasets/{id}/quality: score + history (FR-014).
- GET /datasets/{id}/quality/history: per-run results (US6-AC1, FR-013).
- GET /reports/{id}: drill-down to failing test + failed records + quarantine
  (US6-AC2, FR-015).
"""

from __future__ import annotations

import uuid

PROBLEM_CT = "application/problem+json"


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


def _seed_report(app, ds_id, *, decision="block", overall="failed", tests_failed=1):
    """Create a QualityGate + a GateReport for a dataset."""
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
            created_by="dev@datafoundry.local",
        )
        sess.add(gate)
        sess.flush()
        report = GateReport(
            gate_id=gate.id,
            dataset_id=ds_id,
            run_id=uuid.uuid4(),
            config_version=1,
            decision=GateDecision(decision),
            overall_status=OverallStatus(overall),
            tests_run=2,
            tests_passed=1,
            tests_warned=0,
            tests_failed=tests_failed,
        )
        sess.add(report)
        sess.commit()
        return report.id


class TestQuality:
    def test_get_quality(self, app, client):
        ds_id = _seed_dataset(app)
        _seed_report(app, ds_id)
        response = client.get(f"/api/v1/datasets/{ds_id}/quality")
        assert response.status_code == 200, response.text
        data = response.json()
        assert set(data) == {
            "dataset_id",
            "score",
            "window_start",
            "window_end",
            "history",
        }
        assert data["dataset_id"] == str(ds_id)
        assert 0 <= data["score"] <= 100
        assert len(data["history"]) == 1
        item = data["history"][0]
        assert set(item) == {
            "report_id",
            "decision",
            "overall_status",
            "tests_run",
            "tests_passed",
            "tests_warned",
            "tests_failed",
            "config_version",
            "ran_at",
        }
        assert item["decision"] == "block"
        assert item["overall_status"] == "failed"

    def test_get_quality_empty(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.get(f"/api/v1/datasets/{ds_id}/quality")
        assert response.status_code == 200
        data = response.json()
        assert data["score"] == 100.0
        assert data["history"] == []

    def test_get_quality_unknown_dataset_404(self, app, client):
        response = client.get(f"/api/v1/datasets/{uuid.uuid4()}/quality")
        assert response.status_code == 404

    def test_get_quality_history(self, app, client):
        ds_id = _seed_dataset(app)
        _seed_report(app, ds_id)
        response = client.get(f"/api/v1/datasets/{ds_id}/quality/history")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 1
        assert data["items"][0]["config_version"] == 1


class TestReportDrillDown:
    def test_drill_down(self, app, client):
        ds_id = _seed_dataset(app)
        report_id = _seed_report(app, ds_id)
        response = client.get(f"/api/v1/reports/{report_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert set(data) == {
            "report_id",
            "gate_id",
            "dataset_id",
            "run_id",
            "decision",
            "overall_status",
            "tests_run",
            "tests_passed",
            "tests_warned",
            "tests_failed",
            "config_version",
            "results",
            "quarantine_entries",
        }
        assert data["report_id"] == str(report_id)
        assert data["decision"] == "block"
        assert data["results"] == []
        assert data["quarantine_entries"] == []

    def test_drill_down_unknown_404(self, app, client):
        response = client.get(f"/api/v1/reports/{uuid.uuid4()}")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_CT)
