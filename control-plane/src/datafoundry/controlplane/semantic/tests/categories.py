"""Semantic test categories (feature 006, T025, R-04).

calculation, reconciliation, relationship, filter; run at publish time AND on
schedule against production data (FR-014). Each category returns a
:class:`SemanticTestResult` with status + measured value.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from datafoundry.controlplane.db.models import SemanticTestStatus
from datafoundry.controlplane.semantic.tests.base import SemanticTest, SemanticTestResult

if TYPE_CHECKING:
    from datafoundry.controlplane.semantic.tests.registry import SemanticTestRegistry


def _passed(measured: dict[str, Any] | None = None) -> SemanticTestResult:
    return SemanticTestResult(status=SemanticTestStatus.passed, measured_value=measured or {})


def _failed(measured: dict[str, Any] | None = None) -> SemanticTestResult:
    return SemanticTestResult(status=SemanticTestStatus.failed, measured_value=measured or {})


class CalculationTest(SemanticTest):
    """Metric produces the expected result on reference data (FR-004)."""

    def evaluate(self, conn: Any, *, gateway: Any, **context: Any) -> SemanticTestResult:
        expected = self.parameters.get("expected_value")
        actual = context.get("actual_value")
        tolerance_pct = self.parameters.get("tolerance_pct", 0.0)
        if actual is None:
            return _failed({"actual": None, "expected": expected})
        if (
            expected is not None
            and abs(actual - expected) / max(abs(expected), 1e-9) * 100 > tolerance_pct
        ):
            return _failed({"actual": actual, "expected": expected, "tolerance_pct": tolerance_pct})
        return _passed({"actual": actual, "expected": expected})


class ReconciliationTest(SemanticTest):
    """Aggregation reconciles with the underlying dataset (FR-004)."""

    def evaluate(self, conn: Any, *, gateway: Any, **context: Any) -> SemanticTestResult:
        source_dataset = self.parameters.get("source_dataset")
        tolerance_pct = self.parameters.get("tolerance_pct", 0.0)
        actual = context.get("actual_value")
        expected = context.get("expected_value")
        if actual is None or expected is None:
            return _failed({"actual": actual, "expected": expected})
        if abs(actual - expected) / max(abs(expected), 1e-9) * 100 > tolerance_pct:
            return _failed(
                {"actual": actual, "expected": expected, "source_dataset": source_dataset}
            )
        return _passed({"actual": actual, "expected": expected})


class RelationshipTest(SemanticTest):
    """Dimension relationships hold, no fan-out/double-counting (SC-007)."""

    def evaluate(self, conn: Any, *, gateway: Any, **context: Any) -> SemanticTestResult:
        max_fanout = self.parameters.get("max_fanout", 1)
        observed_fanout = context.get("observed_fanout", 0)
        if observed_fanout > max_fanout:
            return _failed({"observed_fanout": observed_fanout, "max_fanout": max_fanout})
        return _passed({"observed_fanout": observed_fanout, "max_fanout": max_fanout})


class FilterTest(SemanticTest):
    """Filters behave as defined (FR-004)."""

    def evaluate(self, conn: Any, *, gateway: Any, **context: Any) -> SemanticTestResult:
        expected_count = self.parameters.get("expected_count")
        actual_count = context.get("actual_count")
        if actual_count is None or (expected_count is not None and actual_count != expected_count):
            return _failed({"actual_count": actual_count, "expected_count": expected_count})
        return _passed({"actual_count": actual_count, "expected_count": expected_count})


def register_all(registry: SemanticTestRegistry) -> None:
    """Register the semantic test category implementations (T025)."""
    registry.register("calculation", CalculationTest)
    registry.register("reconciliation", ReconciliationTest)
    registry.register("relationship", RelationshipTest)
    registry.register("filter", FilterTest)
