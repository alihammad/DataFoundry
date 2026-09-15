"""API router: quality gates (T018, contracts/quality-api.md §1).

- ``POST /datasets/{dataset_id}/gates/{transition}`` — define a gate (FR-001,
  FR-018): validate (all errors at once) -> persist QualityGate + QualityTest
  rows -> audit ``gate.defined``/``gate.updated``. 422 on unknown category,
  invalid severity, no CRITICAL/ERROR test, or secret-scan hit.
- ``GET /datasets/{dataset_id}/gates/{transition}`` — export gate config
  (FR-018): config_yaml + config_hash.
- ``POST /gates/{gate_id}/run`` — run the gate against a batch (FR-001,
  FR-013): evaluate tests -> GateReport -> decision; audit ``gate.run``.
- ``GET /gates/{gate_id}/reports/{report_id}`` — gate report detail with
  per-test results for drill-down (US1-AC3, FR-015).
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db, get_quality_gateway
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.quality_schema import (
    GateConfigError,
    validate_gate_config,
)
from datafoundry.controlplane.config.validation import canonical_yaml
from datafoundry.controlplane.db.models import (
    Dataset,
    GateReport,
    LayerTransition,
    QualityGate,
    QualityTest,
    TestResult,
)
from datafoundry.controlplane.quality.engine import GateNotFoundError, run_gate
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["gates"])


# -- request/response models -----------------------------------------------------


class GateRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    batch_id: uuid.UUID
    environment: str = "production"


class GateDefineResponse(BaseModel):
    gate_id: uuid.UUID
    config_version: int


class GateExportResponse(BaseModel):
    gate_id: uuid.UUID
    transition: str
    config_version: int
    config_yaml: str
    config_hash: str


class TestResultItem(BaseModel):
    test: str
    category: str
    status: str
    failed_record_count: int = 0
    measured_value: dict[str, Any] | None = None


class GateRunResponse(BaseModel):
    report_id: uuid.UUID
    decision: str
    overall_status: str
    tests_run: int
    tests_passed: int
    tests_warned: int
    tests_failed: int
    config_version: int
    results: list[TestResultItem]


class ReportResultItem(BaseModel):
    test_id: uuid.UUID
    test: str
    category: str
    severity: str
    status: str
    failed_record_count: int = 0
    failed_record_refs: list[Any] | None = None
    measured_value: dict[str, Any] | None = None
    duration_ms: int | None = None


class GateReportResponse(BaseModel):
    report_id: uuid.UUID
    gate_id: uuid.UUID
    dataset_id: uuid.UUID
    run_id: uuid.UUID
    config_version: int
    decision: str
    overall_status: str
    tests_run: int
    tests_passed: int
    tests_warned: int
    tests_failed: int
    results: list[ReportResultItem]


# -- helpers ---------------------------------------------------------------------


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


def _get_gate(session: Session, gate_id: uuid.UUID) -> QualityGate:
    gate = session.get(QualityGate, gate_id)
    if gate is None:
        raise NotFoundError(f"no quality gate with id {gate_id}")
    return gate


def _persist_gate(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    transition: str,
    config_yaml: str,
    config_hash: str,
    environment_overrides: dict[str, Any],
    tests: list[dict[str, Any]],
    created_by: str,
) -> QualityGate:
    """Persist a new gate version + its tests; returns the gate."""
    # Next config_version for this (dataset, transition).
    latest = session.execute(
        select(QualityGate.config_version)
        .where(
            QualityGate.dataset_id == dataset_id,
            QualityGate.transition == LayerTransition(transition),
        )
        .order_by(QualityGate.config_version.desc())
        .limit(1)
    ).scalar_one_or_none()
    config_version = (latest or 0) + 1

    gate = QualityGate(
        dataset_id=dataset_id,
        transition=LayerTransition(transition),
        config_version=config_version,
        config_yaml=config_yaml,
        config_hash=config_hash,
        environment_overrides=environment_overrides,
        created_by=created_by,
    )
    session.add(gate)
    session.flush()
    for spec in tests:
        session.add(
            QualityTest(
                gate_id=gate.id,
                name=spec["name"],
                category=spec["category"],
                severity=spec["severity"],
                parameters=spec.get("parameters", {}),
                owner_identity=created_by,
            )
        )
    session.flush()
    return gate


# -- routes ----------------------------------------------------------------------


@router.post(
    "/datasets/{dataset_id}/gates/{transition}",
    status_code=201,
    response_model=GateDefineResponse,
)
def define_gate(
    dataset_id: uuid.UUID,
    transition: str,
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> GateDefineResponse:
    """Define a gate on a layer transition (FR-001, FR-018)."""
    _get_dataset(session, dataset_id)
    if transition not in LayerTransition.__members__.values() and transition not in {
        t.value for t in LayerTransition
    }:
        raise ConfigValidationError(
            [
                {
                    "path": "transition",
                    "code": "invalid_value",
                    "message": f"unknown transition '{transition}'",
                    "remediation": "Use one of the four layer transitions",
                }
            ]
        )

    # Validate: ALL errors at once (unknown category, invalid severity, no
    # CRITICAL/ERROR test, secret-scan hit) — contract rule 5, SC-007.
    config_yaml = canonical_yaml(body)
    try:
        config = validate_gate_config(body, yaml_text=config_yaml)
    except GateConfigError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": _error_path(msg),
                    "code": "invalid_value",
                    "message": msg,
                    "remediation": "Correct the gate config per contracts/gate-config-schema.md",
                }
                for msg in exc.errors
            ]
        ) from exc

    gate = _persist_gate(
        session,
        dataset_id=dataset_id,
        transition=config.transition,
        config_yaml=config_yaml,
        config_hash=_sha256(config_yaml),
        environment_overrides=config.environment_overrides,
        tests=[t.model_dump() for t in config.tests],
        created_by=caller.identity,
    )
    audit = AuditService(session)
    if gate.config_version == 1:
        audit.gate_defined(
            actor=caller.identity,
            dataset_id=dataset_id,
            gate_id=gate.id,
            transition=config.transition,
            config_version=gate.config_version,
            config_hash=gate.config_hash,
        )
    else:
        audit.gate_updated(
            actor=caller.identity,
            dataset_id=dataset_id,
            gate_id=gate.id,
            transition=config.transition,
            config_version=gate.config_version,
            config_hash=gate.config_hash,
        )
    return GateDefineResponse(gate_id=gate.id, config_version=gate.config_version)


@router.get(
    "/datasets/{dataset_id}/gates/{transition}",
    response_model=GateExportResponse,
)
def export_gate(
    dataset_id: uuid.UUID,
    transition: str,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> GateExportResponse:
    """Export the latest gate config for a transition (FR-018)."""
    _get_dataset(session, dataset_id)
    gate = session.execute(
        select(QualityGate)
        .where(
            QualityGate.dataset_id == dataset_id,
            QualityGate.transition == LayerTransition(transition),
        )
        .order_by(QualityGate.config_version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if gate is None:
        raise NotFoundError(f"no gate defined for transition '{transition}'")
    return GateExportResponse(
        gate_id=gate.id,
        transition=gate.transition.value,
        config_version=gate.config_version,
        config_yaml=gate.config_yaml,
        config_hash=f"sha256:{gate.config_hash}",
    )


@router.post(
    "/gates/{gate_id}/run",
    response_model=GateRunResponse,
)
def run_gate_endpoint(
    gate_id: uuid.UUID,
    body: GateRunRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    gateway=Depends(get_quality_gateway),
) -> GateRunResponse:
    """Run the gate against a batch (FR-001, FR-013)."""
    try:
        report = run_gate(
            session,
            gateway=gateway,
            gate_id=gate_id,
            run_id=body.run_id,
            batch_id=body.batch_id,
            environment=body.environment,
        )
    except GateNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    session.flush()

    results = session.execute(select(TestResult).where(TestResult.report_id == report.id)).scalars()
    test_names = {t.id: t for t in session.execute(select(QualityTest)).scalars()}
    items = []
    for result in results:
        test = test_names.get(result.test_id)
        items.append(
            TestResultItem(
                test=test.name if test else str(result.test_id),
                category=test.category.value if test else "unknown",
                status=result.status.value,
                failed_record_count=result.failed_record_count,
                measured_value=result.measured_value,
            )
        )

    AuditService(session).gate_run(
        actor=caller.identity,
        dataset_id=report.dataset_id,
        gate_id=report.gate_id,
        report_id=report.id,
        run_id=report.run_id,
        decision=report.decision.value,
        config_version=report.config_version,
    )
    return GateRunResponse(
        report_id=report.id,
        decision=report.decision.value,
        overall_status=report.overall_status.value,
        tests_run=report.tests_run,
        tests_passed=report.tests_passed,
        tests_warned=report.tests_warned,
        tests_failed=report.tests_failed,
        config_version=report.config_version,
        results=items,
    )


@router.get(
    "/gates/{gate_id}/reports/{report_id}",
    response_model=GateReportResponse,
)
def get_gate_report(
    gate_id: uuid.UUID,
    report_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> GateReportResponse:
    """Gate report detail with per-test results (US1-AC3, FR-015)."""
    _get_gate(session, gate_id)
    report = session.get(GateReport, report_id)
    if report is None or report.gate_id != gate_id:
        raise NotFoundError(f"no report {report_id} for gate {gate_id}")

    results = session.execute(select(TestResult).where(TestResult.report_id == report.id)).scalars()
    tests = {t.id: t for t in session.execute(select(QualityTest)).scalars()}
    items = []
    for result in results:
        test = tests.get(result.test_id)
        items.append(
            ReportResultItem(
                test_id=result.test_id,
                test=test.name if test else str(result.test_id),
                category=test.category.value if test else "unknown",
                severity=test.severity.value if test else "unknown",
                status=result.status.value,
                failed_record_count=result.failed_record_count,
                failed_record_refs=result.failed_record_refs,
                measured_value=result.measured_value,
                duration_ms=result.duration_ms,
            )
        )
    return GateReportResponse(
        report_id=report.id,
        gate_id=report.gate_id,
        dataset_id=report.dataset_id,
        run_id=report.run_id,
        config_version=report.config_version,
        decision=report.decision.value,
        overall_status=report.overall_status.value,
        tests_run=report.tests_run,
        tests_passed=report.tests_passed,
        tests_warned=report.tests_warned,
        tests_failed=report.tests_failed,
        results=items,
    )


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()


def _error_path(message: str) -> str:
    """Best-effort path extraction from a validation message."""
    if ":" in message:
        return message.split(":", 1)[0].strip()
    return "$"
