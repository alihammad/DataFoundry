"""Quality score + history computation (feature 004, T044, R-07).

- :func:`compute_score` — deterministic quality score (0-100) for a dataset
  from recent gate results (FR-014). Each report contributes by its overall
  status: passed=100, warning=70, failed=0; the score is the mean over the
  recent window.
- :func:`history` — per-run results for trend (US6-AC1, FR-013).
- :func:`drill_down` — a report's per-test results + failed-record refs +
  related quarantine entries (US6-AC2, FR-015).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from datafoundry.controlplane.db.models import (
    GateReport,
    OverallStatus,
    QuarantineEntry,
    TestResult,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

#: Default window over which the score is computed (FR-014).
DEFAULT_WINDOW_DAYS = 30

#: Per-status contribution to the score (deterministic, R-07).
_STATUS_SCORE = {
    OverallStatus.passed: 100.0,
    OverallStatus.warning: 70.0,
    OverallStatus.failed: 0.0,
    OverallStatus.error: 0.0,
}


def compute_score(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> float:
    """Compute the deterministic quality score for a dataset (FR-014).

    Mean of per-report status contributions over the recent window. No reports
    in the window yields 100.0 (no evidence of failure).
    """
    since = datetime.now(UTC) - timedelta(days=window_days)
    reports = list(
        session.scalars(
            select(GateReport)
            .where(
                GateReport.dataset_id == dataset_id,
                GateReport.created_at >= since,
            )
            .order_by(GateReport.created_at.desc())
        ).all()
    )
    if not reports:
        return 100.0
    total = sum(_STATUS_SCORE.get(r.overall_status, 0.0) for r in reports)
    return round(total / len(reports), 2)


def history(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Per-run results for trend (US6-AC1, FR-013)."""
    reports = list(
        session.scalars(
            select(GateReport)
            .where(GateReport.dataset_id == dataset_id)
            .order_by(GateReport.created_at.desc())
            .limit(limit)
        ).all()
    )
    return [
        {
            "report_id": r.id,
            "decision": r.decision.value,
            "overall_status": r.overall_status.value,
            "tests_run": r.tests_run,
            "tests_passed": r.tests_passed,
            "tests_warned": r.tests_warned,
            "tests_failed": r.tests_failed,
            "config_version": r.config_version,
            "ran_at": r.created_at,
        }
        for r in reports
    ]


def drill_down(
    session: Session,
    *,
    report_id: uuid.UUID,
) -> dict[str, Any]:
    """A report's per-test results + failed-record refs + quarantine (FR-015).

    Quarantine entries are matched to the report's run via ``batch_id`` (the
    report's run_id is the run being gated; quarantine entries carry the
    batch_id of the affected batch).
    """
    report = session.get(GateReport, report_id)
    if report is None:
        raise KeyError(f"no gate report with id {report_id}")

    results = list(
        session.scalars(select(TestResult).where(TestResult.report_id == report.id)).all()
    )
    quarantine = list(
        session.scalars(
            select(QuarantineEntry).where(QuarantineEntry.dataset_id == report.dataset_id)
        ).all()
    )
    return {
        "report_id": report.id,
        "gate_id": report.gate_id,
        "dataset_id": report.dataset_id,
        "run_id": report.run_id,
        "decision": report.decision.value,
        "overall_status": report.overall_status.value,
        "tests_run": report.tests_run,
        "tests_passed": report.tests_passed,
        "tests_warned": report.tests_warned,
        "tests_failed": report.tests_failed,
        "config_version": report.config_version,
        "results": [
            {
                "test_id": r.test_id,
                "status": r.status.value,
                "failed_record_count": r.failed_record_count,
                "failed_record_refs": r.failed_record_refs,
                "measured_value": r.measured_value,
                "duration_ms": r.duration_ms,
            }
            for r in results
        ],
        "quarantine_entries": [
            {
                "entry_id": q.id,
                "batch_id": q.batch_id,
                "payload_ref": q.payload_ref,
                "failure_reason": q.failure_reason,
                "failed_test": q.failed_test,
            }
            for q in quarantine
        ],
    }


__all__ = ["compute_score", "drill_down", "history"]
