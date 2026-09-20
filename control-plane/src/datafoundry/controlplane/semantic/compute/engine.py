"""Metric computation over Gold/Silver (feature 006, T010/T018, R-02).

Compile a metric's declarative ``formula`` (measure + aggregation + optional
filter + dimensions) to a DuckDB query over Gold/Silver datasets read through
the gateway. The same definition produces identical results on both clouds
(FR-013, SC-008).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import duckdb


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


def compile_metric_query(
    *,
    measure_column: str,
    aggregation: str,
    dataset: str,
    filter_spec: dict[str, Any] | None,
    dimensions: list[str],
) -> str:
    """Compile a metric formula to a DuckDB SQL query (R-02).

    Returns a SQL string selecting the aggregated value (and dimension
    columns when present) from the dataset table.
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

    if filter_spec:
        where = " AND ".join(f"{k} = '{v}'" for k, v in filter_spec.items())
        sql += f" WHERE {where}"

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
) -> MetricResult:
    """Compute a metric over a dataset read through the gateway (R-02).

    Reads the dataset's records via the gateway (never a cloud SDK directly),
    registers them in an in-memory DuckDB connection, and runs the compiled
    query. Returns the value plus provenance (definition version, dataset
    versions, freshness, quality state).
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
    )

    conn = duckdb.connect()
    try:
        conn.register(dataset, table)
        rows = conn.execute(sql).fetchall()
        if not rows:
            value = 0
        elif len(rows) == 1 and len(rows[0]) == 1:
            value = rows[0][0] or 0
        else:
            # Grouped result: sum the per-group values for a scalar metric.
            value = sum(row[-1] or 0 for row in rows)
    finally:
        conn.close()

    return MetricResult(
        value=value,
        definition_version=definition_version,
        dataset_versions={dataset: meta.get("last_updated")},
        freshness=meta.get("last_updated"),
        quality_state=meta.get("quality_state", "unknown"),
    )
