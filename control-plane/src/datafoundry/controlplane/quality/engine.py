"""Run a gate: evaluate tests -> report -> decision (T010, R-02/R-03).

The engine loads a :class:`QualityGate` and its tests, resolves each test's
implementation from the registry, evaluates it against the dataset's records
(via the gateway), aggregates a :class:`GateReport`, and records a
:class:`TestResult` per test. The gate config version active when the batch
started is recorded with the results (FR-013, R-03).
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.db.models import (
    GateReport,
    QualityGate,
    QualityTest,
    TestResult,
)
from datafoundry.controlplane.quality.gates.gate import (
    GateTestOutcome,
    decide,
)
from datafoundry.controlplane.quality.tests.registry import resolve_test
from sqlalchemy import select
from sqlalchemy.orm import Session


class GateNotFoundError(KeyError):
    """Raised when a gate id does not exist."""


def _load_gate(session: Session, gate_id: uuid.UUID) -> QualityGate:
    gate = session.get(QualityGate, gate_id)
    if gate is None:
        raise GateNotFoundError(f"no quality gate with id {gate_id}")
    return gate


def run_gate(
    session: Session,
    *,
    gateway: Any,
    gate_id: uuid.UUID,
    run_id: uuid.UUID,
    batch_id: uuid.UUID,
    environment: str = "production",
) -> GateReport:
    """Run a gate against a batch and persist the report + per-test results.

    ``gateway`` is a :class:`QualityGateway` (live or simulated). The dataset's
    layer is derived from the gate's transition target (bronze_to_silver ->
    silver, etc.) so the engine reads the correct zone.
    """
    gate = _load_gate(session, gate_id)
    tests = session.scalars(
        select(QualityTest).where(QualityTest.gate_id == gate.id).order_by(QualityTest.name)
    ).all()

    layer = _target_layer(gate.transition.value)
    outcomes: list[GateTestOutcome] = []
    results: list[TestResult] = []

    for test in tests:
        impl_cls = resolve_test(test.category.value)
        impl = impl_cls(
            name=test.name,
            category=test.category.value,
            severity=test.severity,
            parameters=dict(test.parameters or {}),
        )
        data, context = _load_test_data(gateway, gate.dataset_id, layer, test, batch_id)
        result = impl.run(data, **context)
        outcomes.append(
            GateTestOutcome(
                name=test.name,
                category=test.category.value,
                severity=test.severity,
                result=result,
            )
        )
        results.append(result)

    decision = decide(
        outcomes,
        environment=environment,
        environment_overrides=dict(gate.environment_overrides or {}),
    )

    report = GateReport(
        gate_id=gate.id,
        dataset_id=gate.dataset_id,
        run_id=run_id,
        config_version=gate.config_version,
        decision=decision.decision,
        overall_status=decision.overall_status,
        tests_run=decision.tests_run,
        tests_passed=decision.tests_passed,
        tests_warned=decision.tests_warned,
        tests_failed=decision.tests_failed,
    )
    session.add(report)
    session.flush()

    for test, _outcome, result in zip(tests, outcomes, results, strict=True):
        session.add(
            TestResult(
                test_id=test.id,
                report_id=report.id,
                status=result.status,
                measured_value=result.measured_value,
                failed_record_count=result.failed_record_count,
                failed_record_refs=result.failed_record_refs,
                duration_ms=result.duration_ms,
            )
        )
    session.flush()
    return report


def _target_layer(transition: str) -> str:
    """Map a transition to the layer the gate evaluates (the target zone)."""
    return {
        "ingestion_to_bronze": "bronze",
        "bronze_to_silver": "silver",
        "silver_to_gold": "gold",
        "gold_to_consumable": "gold",
    }[transition]


def _load_test_data(
    gateway: Any,
    dataset_id: uuid.UUID,
    layer: str,
    test: QualityTest,
    batch_id: uuid.UUID,
) -> tuple[Any, dict[str, Any]]:
    """Load the data + context a test needs to evaluate.

    Record-level categories read the zone table via the gateway; SQL-based
    categories receive a DuckDB connection over the same table. The simulated
    gateway's fault hooks surface as context flags so offline tests exercise
    the failure paths.
    """
    category = test.category.value
    context: dict[str, Any] = {"batch_id": batch_id, "dataset_id": dataset_id, "layer": layer}

    if category in _SQL_CATEGORIES:
        import duckdb

        table = gateway.read_table(str(dataset_id), layer)
        con = duckdb.connect()
        con.register("zone", table)
        context["row_count"] = table.num_rows
        return con, context

    table = gateway.read_table(str(dataset_id), layer)
    context["row_count"] = table.num_rows
    # Surface simulated fault hooks as context flags for the placeholder
    # freshness/volume implementations (T016/T017 replace these).
    context["stale"] = _has_fault(gateway, dataset_id, "stale")
    context["volume_anomaly"] = _has_fault(gateway, dataset_id, "volume")
    return table, context


#: Categories evaluated with DuckDB (R-02).
_SQL_CATEGORIES = frozenset(
    {"reconciliation", "distribution", "business_rule", "volume", "freshness", "statistical"}
)


def _has_fault(gateway: Any, dataset_id: uuid.UUID, kind: str) -> bool:
    """Whether the simulated gateway has a fault hook active for a dataset."""
    faults = getattr(gateway, "_faults", None)
    if faults is None:
        return False
    return f"{kind}:{dataset_id}" in faults


__all__ = ["GateNotFoundError", "run_gate"]
