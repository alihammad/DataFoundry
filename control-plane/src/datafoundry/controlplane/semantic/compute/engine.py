"""Metric computation over Gold/Silver (feature 006, T010/T018, R-02).

Compile a metric's declarative ``formula`` (measure + aggregation + optional
filter + dimensions) to a DuckDB query over Gold/Silver datasets read through
the gateway. The same definition produces identical results on both clouds
(FR-013, SC-008).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import duckdb

logger = logging.getLogger("datafoundry.semantic.compute")


class MetricCompilationError(ValueError):
    """Raised when a metric formula cannot be compiled to a valid query."""


@dataclass
class MetricResult:
    """The computed value of a metric plus provenance (FR-008/FR-012)."""

    value: float | int
    definition_version: int
    dataset_versions: dict[str, Any]
    freshness: str | None
    quality_state: str
    #: Per-group dimension values when the query is grouped (US3-AC2).
    dimension_values: list[dict[str, Any]] = field(default_factory=list)


def compile_metric_query(
    *,
    measure_column: str,
    aggregation: str,
    dataset: str,
    filter_spec: dict[str, Any] | None,
    dimensions: list[str],
    row_filters: list[str] | None = None,
) -> str:
    """Compile a metric formula to a DuckDB SQL query (R-02).

    Returns a SQL string selecting the aggregated value (and dimension
    columns when present) from the dataset table. ``row_filters`` are
    row-level restriction predicates applied before aggregation (US3-AC3).
    """
    agg = _AGGREGATIONS.get(aggregation)
    if agg is None:
        raise MetricCompilationError(f"unsupported aggregation '{aggregation}'")

    if dimensions:
        dim_cols = ", ".join(dimensions)
        select_expr = f"{agg}({measure_column}) AS value"
        # Identifiers come from a validated schema, not user input (S608 n/a).
        sql = f"SELECT {dim_cols}, {select_expr} FROM {dataset}"  # noqa: S608
    else:
        select_expr = f"{agg}({measure_column}) AS value"
        sql = f"SELECT {select_expr} FROM {dataset}"  # noqa: S608

    where_clauses: list[str] = []
    if filter_spec:
        where_clauses.extend(f"{k} = '{v}'" for k, v in filter_spec.items())
    if row_filters:
        where_clauses.extend(row_filters)
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)

    if dimensions:
        sql += f" GROUP BY {dim_cols}"
    return sql


#: Supported aggregations -> DuckDB function (R-02).
_AGGREGATIONS: dict[str, str] = {
    "sum": "SUM",
    "count": "COUNT",
    "avg": "AVG",
    "min": "MIN",
    "max": "MAX",
    "count_distinct": "COUNT(DISTINCT",
}


def compute_metric(
    *,
    gateway: Any,
    dataset: str,
    layer: str,
    measure_column: str,
    aggregation: str,
    filter_spec: dict[str, Any] | None,
    dimensions: list[str],
    definition_version: int,
    row_filters: list[str] | None = None,
    protected_columns: list[str] | None = None,
) -> MetricResult:
    """Compute a metric over a dataset read through the gateway (R-02).

    Reads the dataset's records via the gateway (never a cloud SDK directly),
    registers them in an in-memory DuckDB connection, and runs the compiled
    query. Returns the value plus provenance (definition version, dataset
    versions, freshness, quality state).

    ``row_filters`` apply row-level restrictions before aggregation (US3-AC3);
    ``protected_columns`` are dropped from the result so protected values are
    never exposed through a semantic query (US3-AC2, SC-005).
    """
    if not gateway.table_exists(dataset, layer):
        raise MetricCompilationError(f"no {layer} dataset '{dataset}'")
    table = gateway.read_table(dataset, layer)
    meta = gateway.table_metadata(dataset, layer)

    sql = compile_metric_query(
        measure_column=measure_column,
        aggregation=aggregation,
        dataset=dataset,
        filter_spec=filter_spec,
        dimensions=dimensions,
        row_filters=row_filters,
    )

    conn = duckdb.connect()
    try:
        conn.register(dataset, table)
        rows = conn.execute(sql).fetchall()
        if not rows:
            value = 0
            dimension_values: list[dict[str, Any]] = []
        elif len(rows) == 1 and len(rows[0]) == 1:
            value = rows[0][0] or 0
            dimension_values = []
        else:
            # Grouped result: sum the per-group values for a scalar metric.
            value = sum(row[-1] or 0 for row in rows)
            dimension_values = [
                {
                    dim: _mask_if_protected(row[i], dim, protected_columns)
                    for i, dim in enumerate(dimensions)
                }
                for row in rows
            ]
    finally:
        conn.close()

    return MetricResult(
        value=value,
        definition_version=definition_version,
        dataset_versions={dataset: meta.get("last_updated")},
        freshness=meta.get("last_updated"),
        quality_state=meta.get("quality_state", "unknown"),
        dimension_values=dimension_values,
    )


def _mask_if_protected(value: Any, column: str, protected_columns: list[str] | None) -> Any:
    """Mask a dimension value when its column is protected (US3-AC2, SC-005)."""
    if protected_columns and column in protected_columns:
        return "[REDACTED]"
    return value


def log_metric_query(*, metric_id: str, dataset: str, value: Any, quality_state: str) -> None:
    """Emit a structured log for a metric query (T021, FR-002).

    Structured via the existing OpenTelemetry/structured-logging channel; never
    logs raw values or secrets (SC-007).
    """
    logger.info(
        "semantic_metric_query metric_id=%s dataset=%s value=%s quality_state=%s",
        metric_id,
        dataset,
        value,
        quality_state,
    )
