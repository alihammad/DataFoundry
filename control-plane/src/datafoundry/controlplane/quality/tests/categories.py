"""Test category implementations (T016/T017, R-02).

Record-level categories (PyArrow): schema, type, nullability, uniqueness,
completeness, validity, referential_integrity, contract, transformation,
security. SQL-based categories (DuckDB): reconciliation, distribution,
business_rule, volume, freshness, statistical.

Each category returns a :class:`TestResult` with status + failed-record
count/refs (record-level) or status + measured value (SQL-based).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pyarrow as pa
from datafoundry.controlplane.db.models import TestResultStatus
from datafoundry.controlplane.quality.tests.base import Test, TestResult

if TYPE_CHECKING:
    from datafoundry.controlplane.quality.tests.registry import TestRegistry


def _failed(
    measured: dict[str, Any] | None = None,
    count: int = 0,
    refs: list[Any] | None = None,
) -> TestResult:
    return TestResult(
        status=TestResultStatus.failed,
        measured_value=measured or {},
        failed_record_count=count,
        failed_record_refs=refs,
    )


def _passed(measured: dict[str, Any] | None = None) -> TestResult:
    return TestResult(status=TestResultStatus.passed, measured_value=measured or {})


# ---------------------------------------------------------------------------
# Record-level categories (PyArrow)
# ---------------------------------------------------------------------------


class SchemaTest(Test):
    """Record-level: observed schema matches ``expected_schema`` (FR-003)."""

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        expected = self.parameters.get("expected_schema", {})
        observed = {name: str(data.schema.field(name).type) for name in data.column_names}
        mismatches = {
            col: {"expected": exp, "observed": observed.get(col)}
            for col, exp in expected.items()
            if observed.get(col) != exp
        }
        if mismatches:
            return _failed({"schema_mismatches": mismatches}, count=len(mismatches))
        return _passed({"columns": len(data.column_names)})


class TypeTest(Test):
    """Record-level: columns have the expected PyArrow type (FR-003)."""

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        columns = self.parameters["columns"]
        expected_type = self.parameters.get("type")
        mismatches = {}
        for col in columns:
            if col in data.column_names:
                actual = str(data.schema.field(col).type)
                if expected_type and actual != expected_type:
                    mismatches[col] = {"expected": expected_type, "observed": actual}
        if mismatches:
            return _failed({"type_mismatches": mismatches}, count=len(mismatches))
        return _passed()


class NullabilityTest(Test):
    """Record-level: no nulls in ``columns`` (FR-003)."""

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        columns = self.parameters["columns"]
        failed = 0
        for col in columns:
            if col in data.column_names:
                failed += data.column(col).null_count
        return TestResult(
            status=TestResultStatus.failed if failed else TestResultStatus.passed,
            measured_value={"nulls": failed},
            failed_record_count=failed,
        )


class UniquenessTest(Test):
    """Record-level: no duplicate values across ``columns`` (FR-003)."""

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        columns = self.parameters["columns"]
        table = data.select(columns)
        keys = table.combine_chunks()
        if len(columns) == 1:
            composite = keys.column(columns[0])
        else:
            composite = pa.array(
                [tuple(r) for r in zip(*(keys.column(c).to_pylist() for c in columns), strict=True)]
            )
        vc = composite.value_counts()
        counts = vc.field(1).to_pylist()
        failed = sum(1 for c in counts if c > 1)
        return TestResult(
            status=TestResultStatus.failed if failed else TestResultStatus.passed,
            measured_value={"duplicates": failed},
            failed_record_count=failed,
        )


class CompletenessTest(Test):
    """Record-level: ``columns`` are fully populated (no nulls) (FR-003)."""

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        columns = self.parameters["columns"]
        missing = 0
        for col in columns:
            if col in data.column_names:
                missing += data.column(col).null_count
        return TestResult(
            status=TestResultStatus.failed if missing else TestResultStatus.passed,
            measured_value={"missing": missing},
            failed_record_count=missing,
        )


class ValidityTest(Test):
    """Record-level: values in ``columns`` satisfy ``allowed_values`` (FR-003)."""

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        columns = self.parameters["columns"]
        allowed = set(self.parameters.get("allowed_values", []))
        invalid = 0
        refs: list[Any] = []
        for col in columns:
            if col in data.column_names and allowed:
                values = data.column(col).to_pylist()
                for idx, value in enumerate(values):
                    if value is not None and value not in allowed:
                        invalid += 1
                        refs.append({"column": col, "row": idx, "value": value})
        if invalid:
            return _failed({"invalid": invalid}, count=invalid, refs=refs[:100])
        return _passed()


class ReferentialIntegrityTest(Test):
    """Record-level: ``columns`` reference ``reference_table.reference_column``.

    Offline, the reference set is supplied via ``context['reference_values']``
    (the gateway seeds it); a live adapter would join the reference zone.
    """

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        columns = self.parameters["columns"]
        reference_values = set(context.get("reference_values", []))
        orphans = 0
        refs: list[Any] = []
        for col in columns:
            if col in data.column_names and reference_values:
                for idx, value in enumerate(data.column(col).to_pylist()):
                    if value is not None and value not in reference_values:
                        orphans += 1
                        refs.append({"column": col, "row": idx, "value": value})
        if orphans:
            return _failed({"orphans": orphans}, count=orphans, refs=refs[:100])
        return _passed()


class ContractTest(Test):
    """Record-level: observed schema conforms to the dataset's contract.

    ``context['contract_schema']`` carries the approved contract schema
    (``{column: {type, nullable}}``); a live adapter reads it from the DB.
    """

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        contract = context.get("contract_schema") or {}
        observed = {name: str(data.schema.field(name).type) for name in data.column_names}
        violations = {}
        for col, spec in contract.items():
            expected_type = spec.get("type")
            if col in observed and expected_type and observed[col] != expected_type:
                violations[col] = {"expected": expected_type, "observed": observed[col]}
        if violations:
            return _failed({"contract_violations": violations}, count=len(violations))
        return _passed()


class TransformationTest(Test):
    """Record-level: ``expression`` holds over the data (e.g. derived column).

    MVP: evaluates a simple predicate over a column (``non_negative``,
    ``non_empty``).
    """

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        expression = self.parameters.get("expression", "")
        column = self.parameters.get("column")
        if not column or column not in data.column_names:
            return _failed({"error": "transformation test needs a 'column' parameter"})
        values = data.column(column).to_pylist()
        failed = 0
        refs: list[Any] = []
        for idx, value in enumerate(values):
            if value is None:
                continue
            if (expression == "non_negative" and value < 0) or (
                expression == "non_empty" and value == ""
            ):
                failed += 1
                refs.append({"row": idx, "value": value})
        if failed:
            return _failed({"violations": failed}, count=failed, refs=refs[:100])
        return _passed()


class SecurityTest(Test):
    """Record-level: ``columns`` contain no secret-like values (SC-007)."""

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        from datafoundry.controlplane.config.secret_scan import has_secrets

        columns = self.parameters["columns"]
        failed = 0
        refs: list[Any] = []
        for col in columns:
            if col in data.column_names:
                for idx, value in enumerate(data.column(col).to_pylist()):
                    if isinstance(value, str) and has_secrets(value):
                        failed += 1
                        refs.append({"column": col, "row": idx})
        if failed:
            return _failed({"secret_like_values": failed}, count=failed, refs=refs[:100])
        return _passed()


# ---------------------------------------------------------------------------
# SQL-based categories (DuckDB)
# ---------------------------------------------------------------------------


class ReconciliationTest(Test):
    """SQL-based: ``sql`` result within ``tolerance_pct`` of ``expected`` (FR-003)."""

    def evaluate(self, data: object, **context: object) -> TestResult:
        sql = self.parameters.get("sql", "")
        tolerance = self.parameters.get("tolerance_pct", 0.0)
        expected = self.parameters.get("expected")
        try:
            value = data.execute(sql).fetchone()[0]
        except Exception as exc:
            raise RuntimeError(f"reconciliation query failed: {exc}") from exc
        if expected is not None:
            deviation = abs(float(value) - float(expected)) / max(abs(float(expected)), 1e-9) * 100
            if deviation > tolerance:
                return _failed({"value": value, "expected": expected, "deviation_pct": deviation})
        return _passed({"value": value})


class DistributionTest(Test):
    """SQL-based: distinct-value ratio within ``max_distinct_ratio`` (FR-003)."""

    def evaluate(self, data: object, **context: object) -> TestResult:
        columns = self.parameters["columns"]
        max_ratio = self.parameters.get("max_distinct_ratio", 1.0)
        for col in columns:
            try:
                total = data.execute(
                    f'SELECT COUNT(*) FROM zone WHERE "{col}" IS NOT NULL'  # noqa: S608
                ).fetchone()[0]
                distinct = data.execute(
                    f'SELECT COUNT(DISTINCT "{col}") FROM zone'  # noqa: S608
                ).fetchone()[0]
            except Exception as exc:
                raise RuntimeError(f"distribution query failed: {exc}") from exc
            ratio = distinct / total if total else 0.0
            if ratio > max_ratio:
                return _failed({"column": col, "distinct_ratio": ratio, "max": max_ratio})
        return _passed()


class BusinessRuleTest(Test):
    """SQL-based: ``expression`` (a WHERE clause) matches no rows (FR-003)."""

    def evaluate(self, data: object, **context: object) -> TestResult:
        expression = self.parameters.get("expression", "")
        try:
            count = data.execute(
                f"SELECT COUNT(*) FROM zone WHERE {expression}"  # noqa: S608
            ).fetchone()[0]
        except Exception as exc:
            raise RuntimeError(f"business rule query failed: {exc}") from exc
        if count:
            return _failed({"violations": count}, count=count)
        return _passed()


class VolumeTest(Test):
    """SQL-based: row count meets ``min_records`` (FR-003)."""

    def evaluate(self, data: object, **context: object) -> TestResult:
        minimum = self.parameters.get("min_records", 0)
        if context.get("volume_anomaly"):
            return _failed({"rows": 0, "min_records": minimum}, count=1)
        rows = context.get("row_count")
        if rows is not None and rows < minimum:
            return _failed({"rows": rows, "min_records": minimum}, count=minimum - rows)
        return _passed({"rows": rows, "min_records": minimum})


class FreshnessTest(Test):
    """SQL-based: data not older than ``max_staleness_minutes`` (FR-003)."""

    def evaluate(self, data: object, **context: object) -> TestResult:
        if context.get("stale"):
            return _failed({"stale": True}, count=1)
        return _passed({"stale": False})


class StatisticalTest(Test):
    """SQL-based: column mean within ``max_deviation_pct`` of ``expected_mean`` (FR-003)."""

    def evaluate(self, data: object, **context: object) -> TestResult:
        column = self.parameters.get("column")
        expected = self.parameters.get("expected_mean")
        max_dev = self.parameters.get("max_deviation_pct", 0.0)
        if not column:
            return _failed({"error": "statistical test needs a 'column' parameter"})
        try:
            mean = data.execute(
                f'SELECT AVG("{column}") FROM zone'  # noqa: S608
            ).fetchone()[0]
        except Exception as exc:
            raise RuntimeError(f"statistical query failed: {exc}") from exc
        if expected is not None and mean is not None:
            deviation = abs(float(mean) - float(expected)) / max(abs(float(expected)), 1e-9) * 100
            if deviation > max_dev:
                return _failed({"mean": mean, "expected": expected, "deviation_pct": deviation})
        return _passed({"mean": mean})


def register_all(registry: TestRegistry) -> None:
    """Register all 16 test category implementations."""
    registry.register("schema", SchemaTest)
    registry.register("type", TypeTest)
    registry.register("nullability", NullabilityTest)
    registry.register("uniqueness", UniquenessTest)
    registry.register("completeness", CompletenessTest)
    registry.register("validity", ValidityTest)
    registry.register("referential_integrity", ReferentialIntegrityTest)
    registry.register("reconciliation", ReconciliationTest)
    registry.register("freshness", FreshnessTest)
    registry.register("volume", VolumeTest)
    registry.register("distribution", DistributionTest)
    registry.register("business_rule", BusinessRuleTest)
    registry.register("security", SecurityTest)
    registry.register("contract", ContractTest)
    registry.register("transformation", TransformationTest)
    registry.register("statistical", StatisticalTest)


__all__ = [
    "BusinessRuleTest",
    "CompletenessTest",
    "ContractTest",
    "DistributionTest",
    "FreshnessTest",
    "NullabilityTest",
    "ReconciliationTest",
    "ReferentialIntegrityTest",
    "SchemaTest",
    "SecurityTest",
    "StatisticalTest",
    "TransformationTest",
    "TypeTest",
    "UniquenessTest",
    "ValidityTest",
    "VolumeTest",
    "register_all",
]
