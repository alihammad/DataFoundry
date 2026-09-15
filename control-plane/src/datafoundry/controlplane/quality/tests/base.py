"""Test ABC (T008, R-01).

Every quality test category implements :class:`Test` with an ``evaluate``
operation returning a :class:`TestResult`. The ABC carries the test's
definition (name, category, severity, parameters) and the effective severity
after per-environment override resolution (FR-005).

The registry (``tests/registry.py``) maps ``category`` -> implementation,
mirroring the capability-registry pattern (FR-015 spirit): adding a test
category = one module + one registration entry, no core change.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from typing import Any

from datafoundry.controlplane.db.models import TestResultStatus, TestSeverity


@dataclass
class TestResult:
    """One test's outcome in one run (spec Key Entity, FR-013).

    Not frozen so :meth:`Test.run` can stamp ``duration_ms`` after evaluation.
    """

    status: TestResultStatus
    measured_value: dict[str, Any] | None = None
    failed_record_count: int = 0
    failed_record_refs: list[Any] | None = None
    duration_ms: int | None = None

    @property
    def passed(self) -> bool:
        return self.status == TestResultStatus.passed


@dataclass
class Test:
    """Base class for a quality test category implementation.

    ``evaluate`` receives the data needed to run the test (a PyArrow table for
    record-level categories, or a DuckDB connection for SQL-based categories)
    and returns a :class:`TestResult`.
    """

    name: str
    category: str
    severity: TestSeverity
    parameters: dict[str, Any] = field(default_factory=dict)

    @abc.abstractmethod
    def evaluate(self, data: Any, **context: Any) -> TestResult:
        """Evaluate the test against ``data``.

        ``data`` is a PyArrow table for record-level categories or a DuckDB
        connection for SQL-based categories (R-02). ``context`` may carry
        additional inputs (e.g. the gateway, dataset id, layer).
        """

    def run(self, data: Any, **context: Any) -> TestResult:
        """Evaluate with timing; infrastructure errors become ``not_run``.

        Fail-closed (FR-002): if evaluation raises, the result is ``not_run``
        so the gate decision blocks rather than silently passing.
        """
        started = time.perf_counter()
        try:
            result = self.evaluate(data, **context)
        except Exception:
            result = TestResult(
                status=TestResultStatus.not_run,
                measured_value={"error": "test could not execute"},
            )
        result.duration_ms = int((time.perf_counter() - started) * 1000)
        return result


__all__ = ["Test", "TestResult"]
