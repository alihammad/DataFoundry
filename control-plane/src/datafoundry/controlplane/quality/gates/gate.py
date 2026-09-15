"""Gate model, decision (PROMOTE/BLOCK), and fail-closed semantics (T009).

A gate is a set of tests bound to a layer transition for a dataset. The
decision function blocks if any CRITICAL/ERROR test fails — or cannot execute
(fail closed, FR-002, R-03). WARNING failures continue with notification;
INFORMATIONAL records only (FR-004).

Per-environment severity resolution (FR-005) applies ``environment_overrides``
from the gate to each test's effective severity before the decision.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from datafoundry.controlplane.config.quality_schema import BLOCKING_SEVERITIES
from datafoundry.controlplane.db.models import (
    GateDecision,
    OverallStatus,
    TestResultStatus,
    TestSeverity,
)
from datafoundry.controlplane.quality.tests.base import TestResult

#: Result statuses that count as a blocking failure for a CRITICAL/ERROR test.
_BLOCKING_STATUSES = frozenset({TestResultStatus.failed, TestResultStatus.not_run})


@dataclass(frozen=True)
class GateTestOutcome:
    """One test's outcome within a gate run, with its effective severity."""

    name: str
    category: str
    severity: TestSeverity
    result: TestResult


@dataclass
class GateDecisionResult:
    """The aggregate decision for a gate run (spec Key Entity, FR-013)."""

    decision: GateDecision
    overall_status: OverallStatus
    tests_run: int = 0
    tests_passed: int = 0
    tests_warned: int = 0
    tests_failed: int = 0
    outcomes: list[GateTestOutcome] = field(default_factory=list)


def resolve_effective_severity(
    severity: TestSeverity,
    *,
    environment: str,
    environment_overrides: dict[str, dict[str, TestSeverity]] | None,
    test_name: str,
) -> TestSeverity:
    """Apply per-environment severity override (FR-005).

    ``environment_overrides`` is ``{env: {test_name: severity}}``. An override
    for the given environment and test name wins; otherwise the base severity
    stands.
    """
    if not environment_overrides:
        return severity
    env_overrides = environment_overrides.get(environment)
    if not env_overrides:
        return severity
    return env_overrides.get(test_name, severity)


def decide(
    outcomes: list[GateTestOutcome],
    *,
    environment: str = "production",
    environment_overrides: dict[str, dict[str, TestSeverity]] | None = None,
) -> GateDecisionResult:
    """Compute the gate decision from per-test outcomes (R-03, FR-002/FR-004).

    BLOCK iff any CRITICAL/ERROR test (after env override) is ``failed`` or
    ``not_run``; otherwise PROMOTE. WARNING/INFORMATIONAL failures are recorded
    but never block.
    """
    tests_run = 0
    tests_passed = 0
    tests_warned = 0
    tests_failed = 0
    blocking_failure = False

    for outcome in outcomes:
        effective = resolve_effective_severity(
            outcome.severity,
            environment=environment,
            environment_overrides=environment_overrides,
            test_name=outcome.name,
        )
        status = outcome.result.status
        tests_run += 1
        if status == TestResultStatus.passed:
            tests_passed += 1
        elif status == TestResultStatus.warning:
            tests_warned += 1
        elif status in _BLOCKING_STATUSES or status == TestResultStatus.error:
            tests_failed += 1
            if effective in BLOCKING_SEVERITIES:
                blocking_failure = True

    if blocking_failure:
        decision = GateDecision.block
        overall = OverallStatus.failed
    elif tests_failed > 0 or tests_warned > 0:
        decision = GateDecision.promote
        overall = OverallStatus.warning
    else:
        decision = GateDecision.promote
        overall = OverallStatus.passed

    return GateDecisionResult(
        decision=decision,
        overall_status=overall,
        tests_run=tests_run,
        tests_passed=tests_passed,
        tests_warned=tests_warned,
        tests_failed=tests_failed,
        outcomes=outcomes,
    )


__all__ = [
    "GateDecisionResult",
    "GateTestOutcome",
    "decide",
    "resolve_effective_severity",
]
