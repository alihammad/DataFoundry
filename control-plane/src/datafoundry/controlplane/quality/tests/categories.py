"""Test category implementations (feature 004).

Record-level categories (PyArrow): schema, type, nullability, uniqueness,
completeness, validity, referential_integrity, contract, transformation,
security. SQL-based categories (DuckDB): reconciliation, distribution,
business_rule, volume, freshness, statistical. Implemented in T016/T017.

This module also owns ``register_all``, which the registry calls to populate
the process-wide :class:`TestRegistry`. A small foundational subset
(uniqueness, nullability, freshness, volume) is registered here so the gate
engine and unit tests are exercisable offline; T016/T017 add the remaining
categories.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pyarrow as pa
from datafoundry.controlplane.db.models import TestResultStatus
from datafoundry.controlplane.quality.tests.base import Test, TestResult

if TYPE_CHECKING:
    from datafoundry.controlplane.quality.tests.registry import TestRegistry


class UniquenessTest(Test):
    """Record-level: no duplicate values across ``columns`` (FR-003)."""

    def evaluate(self, data: pa.Table, **context: object) -> TestResult:
        columns = self.parameters["columns"]
        table = data.select(columns)
        # Count duplicate rows across the key columns: a row is duplicated when
        # its key combination appears more than once.
        keys = table.combine_chunks()
        # Build a single composite key column for multi-column uniqueness.
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


class FreshnessTest(Test):
    """SQL-based: data not older than ``max_staleness_minutes`` (FR-003)."""

    def evaluate(self, data: object, **context: object) -> TestResult:
        # Placeholder: freshness requires a timestamp column + DuckDB. The
        # gateway's ``force_stale_data`` hook drives the failure path offline.
        if context.get("stale"):
            return TestResult(
                status=TestResultStatus.failed,
                measured_value={"stale": True},
                failed_record_count=1,
            )
        return TestResult(status=TestResultStatus.passed, measured_value={"stale": False})


class VolumeTest(Test):
    """SQL-based: row count meets ``min_records`` (FR-003)."""

    def evaluate(self, data: object, **context: object) -> TestResult:
        minimum = self.parameters.get("min_records", 0)
        if context.get("volume_anomaly"):
            return TestResult(
                status=TestResultStatus.failed,
                measured_value={"rows": 0, "min_records": minimum},
                failed_record_count=1,
            )
        rows = context.get("row_count")
        if rows is not None and rows < minimum:
            return TestResult(
                status=TestResultStatus.failed,
                measured_value={"rows": rows, "min_records": minimum},
                failed_record_count=minimum - rows,
            )
        return TestResult(
            status=TestResultStatus.passed,
            measured_value={"rows": rows, "min_records": minimum},
        )


def register_all(registry: TestRegistry) -> None:
    """Register the foundational test category implementations."""
    registry.register("uniqueness", UniquenessTest)
    registry.register("nullability", NullabilityTest)
    registry.register("freshness", FreshnessTest)
    registry.register("volume", VolumeTest)


__all__ = [
    "FreshnessTest",
    "NullabilityTest",
    "UniquenessTest",
    "VolumeTest",
    "register_all",
]
