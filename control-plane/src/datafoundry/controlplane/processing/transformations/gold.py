"""Gold transformation (feature 003, T030).

Aggregation (group_by + measures) and reconciliation against Silver inputs
within ``reconciliation_tolerance`` (FR-010, US3-AC1).
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from datafoundry.controlplane.processing.transformations.base import (
    Transformation,
    TransformationResult,
)


class GoldTransformation(Transformation):
    """Gold-layer transformation (DuckDB aggregation)."""

    logic_type = "gold"

    def apply(
        self,
        *,
        input_table: pa.Table,
        logic: dict[str, Any],
        dedup_keys: list[str] | None = None,
    ) -> TransformationResult:
        """Aggregate the input per the logic's group_by + measures.

        Phase 2 stub: returns the input unchanged. Full aggregation and
        reconciliation land in Phase 5 (T030).
        """
        return TransformationResult(table=input_table, quarantined=[])
