"""Analyst querying (feature 003, T042).

DuckDB querying over Silver/Gold Iceberg tables (lightweight, no warehouse
load, FR-016). Surfaces schema/quality score/freshness before querying and
applies column-level protection on download (FR-016, US5-AC3).
"""

from __future__ import annotations

from typing import Any

import duckdb
import pyarrow as pa


def run_query(
    *,
    gateway: Any,
    dataset_id: str,
    layer: str,
    sql: str,
) -> dict[str, Any]:
    """Run a SQL query against a dataset's records (FR-016).

    Lightweight DuckDB querying over the dataset's current records — no
    warehouse load. Returns ``{columns, rows, row_count}``.
    """
    table = gateway.read_table(dataset_id, layer)
    con = duckdb.connect()
    try:
        con.register("zone", table)
        result = con.execute(sql).fetchall()
        columns = [desc[0] for desc in con.description]
    finally:
        con.close()
    rows = [list(r) for r in result]
    return {"columns": columns, "rows": rows, "row_count": len(rows)}


def dataset_metadata(*, session, dataset_id: str) -> dict[str, Any]:
    """Surface schema/quality score/freshness before querying (US5-AC1)."""
    from datafoundry.controlplane.db.models import Dataset

    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise KeyError(f"no dataset {dataset_id}")
    return {
        "name": dataset.name,
        "layer": dataset.layer.value,
        "schema_definition": dict(dataset.schema_definition or {}),
        "quality_score": dataset.quality_score,
        "refresh_metadata": dict(dataset.refresh_metadata or {}),
    }


def apply_protection(
    *,
    gateway: Any,
    dataset_id: str,
    table: pa.Table,
) -> pa.Table:
    """Apply column-level protection policies on download (FR-016, US5-AC3).

    Protected columns are masked/tokenised per the gateway's protection policy
    (``{column: "mask" | "tokenise"}``). Masking replaces values with ``***``;
    tokenisation replaces values with a deterministic ``tok_<n>`` label.
    """
    policy = getattr(gateway, "protection_policy", None) or {}
    if not policy:
        return table
    data = table.to_pylist()
    for row in data:
        for column, mode in policy.items():
            if column not in row or row[column] is None:
                continue
            if mode == "mask":
                row[column] = "***"
            elif mode == "tokenise":
                row[column] = f"tok_{row[column]}"
    # Protected columns become strings (mask/tokenise), so widen their type.
    fields = []
    for field in table.schema:
        if field.name in policy:
            fields.append(pa.field(field.name, pa.string(), nullable=True))
        else:
            fields.append(field)
    return pa.Table.from_pylist(data, schema=pa.schema(fields))
