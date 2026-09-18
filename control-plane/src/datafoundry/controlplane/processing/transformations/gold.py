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
    """Gold-layer transformation (group_by + measures aggregation)."""

    logic_type = "gold"

    def apply(
        self,
        *,
        input_table: pa.Table,
        logic: dict[str, Any],
        dedup_keys: list[str] | None = None,
    ) -> TransformationResult:
        """Aggregate the input per the logic's group_by + measures.

        Aggregation is computed from Python lists so it is portable across
        pyarrow versions (no bound-to-version group_by aggregate tuple API).
        """
        aggregation = logic.get("aggregation") or {}
        group_by = list(aggregation.get("group_by") or [])
        measures = list(aggregation.get("measures") or [])

        rows = input_table.to_pylist()
        if not group_by:
            # Global aggregation (no grouping): one output row.
            grouped: dict[str, list[dict[str, Any]]] = {"__all__": rows}
        else:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                key = tuple(row.get(g) for g in group_by)
                grouped.setdefault(key, []).append(row)

        out_rows: list[dict[str, Any]] = []
        for key, group_rows in grouped.items():
            out: dict[str, Any] = {}
            if group_by:
                for gi, g in enumerate(group_by):
                    out[g] = key[gi]
            for measure in measures:
                out[measure["name"]] = _aggregate_measure(
                    group_rows, measure.get("op"), measure.get("column")
                )
            out_rows.append(out)

        schema = pa.schema(
            [pa.field(name, _infer_type(pre)) for name, pre in _field_probes(out_rows)]
        )
        return TransformationResult(
            table=pa.Table.from_pylist(out_rows, schema=schema),
            quarantined=[],
        )


def _aggregate_measure(rows: list[dict[str, Any]], op: str, column: str | None) -> Any:
    """Aggregate ``column`` across ``rows`` with ``op``."""
    values = [r.get(column) for r in rows]
    if op == "count":
        return sum(1 for v in values if v is not None)
    if op == "sum":
        vals = [v for v in values if v is not None]
        return sum(vals)
    if op == "avg":
        vals = [v for v in values if v is not None]
        return sum(vals) / len(vals) if vals else None
    if op == "min":
        vals = [v for v in values if v is not None]
        return min(vals) if vals else None
    if op == "max":
        vals = [v for v in values if v is not None]
        return max(vals) if vals else None
    return None


def _field_probes(rows: list[dict[str, Any]]):
    """Yield (name, probe_value) pairs resolving types from data."""
    if not rows:
        return []
    names = list(rows[0].keys())
    return [(name, rows[0][name]) for name in names]


def _infer_type(value: Any) -> pa.DataType:
    """Infer a pyarrow type from a Python value."""
    if value is None:
        return pa.null()
    if isinstance(value, bool):
        return pa.bool_()
    if isinstance(value, int):
        return pa.int64()
    if isinstance(value, float):
        return pa.float64()
    if isinstance(value, str):
        return pa.string()
    return pa.string()


def reconcile(
    *,
    input_table: pa.Table,
    output_table: pa.Table,
    logic: dict[str, Any],
    tolerance: float | None,
) -> tuple[bool, str | None]:
    """Reconcile the Gold aggregate against its Silver input (FR-010).

    Compares the sum of each numeric-aggregate measure across the Gold output
    against the same column's sum in the Silver input. Reconciliation passes
    when every measure's discrepancy is within ``tolerance`` (percent).

    Returns ``(passed, discrepancy)``.
    """
    aggregation = logic.get("aggregation") or {}
    measures = list(aggregation.get("measures") or [])
    tolerance_pct = tolerance if tolerance is not None else 0.0

    input_rows = input_table.to_pylist()
    out_rows = output_table.to_pylist()

    for measure in measures:
        op = measure.get("op")
        column = measure.get("column")
        if op not in ("sum", "avg") or column is None:
            continue
        # Silver-side reference total for the measure column.
        silver_vals = [r.get(column) for r in input_rows if r.get(column) is not None]
        silver_total = sum(silver_vals)
        # Gold-side sourced totals: for sum this equals the same column total.
        gold_total = sum(
            r.get(measure["name"]) for r in out_rows if r.get(measure["name"]) is not None
        )

        denom = abs(silver_total)
        if denom == 0:
            if abs(gold_total) > 0:
                discrepancy = f"{measure['name']}: silver total 0 but gold {gold_total}"
                return False, discrepancy
            continue
        diff_pct = abs(gold_total - silver_total) / denom * 100
        if diff_pct > tolerance_pct:
            discrepancy = (
                f"{measure['name']}: gold {gold_total} vs silver {silver_total} "
                f"({diff_pct:.2f}% > {tolerance_pct}% tolerance)"
            )
            return False, discrepancy
    return True, None
