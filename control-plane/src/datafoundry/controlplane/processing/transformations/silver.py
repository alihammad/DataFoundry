"""Silver transformation (feature 003, T023/T024).

Cleansing, type conversion, standardisation, schema enforcement, dedup per
``dedup_keys``, and malformed-record routing to quarantine (FR-006). Schema
evolution: additive changes (new nullable column) tolerated; breaking changes
(type change, column removal) block promotion (FR-013).
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from datafoundry.controlplane.processing.transformations.base import (
    Transformation,
    TransformationResult,
)

#: ``coerce_type`` target -> PyArrow type.
_COERCE_TYPES = {
    "integer": pa.int64(),
    "string": pa.string(),
    "float": pa.float64(),
    "boolean": pa.bool_(),
    "timestamp": pa.timestamp("us"),
    "date": pa.date32(),
    "binary": pa.binary(),
}


class SilverTransformation(Transformation):
    """Silver-layer transformation (PyArrow record-level)."""

    logic_type = "silver"

    def apply(
        self,
        *,
        input_table: pa.Table,
        logic: dict[str, Any],
        dedup_keys: list[str] | None = None,
    ) -> TransformationResult:
        """Apply cleansing/standardisation/dedup; quarantine malformed rows.

        Malformed rows (type-coercion failures, schema violations) route to
        quarantine with a reason (FR-006); clean rows land in the output.
        """
        cleansing = logic.get("cleansing") or []
        standardisation = logic.get("standardisation") or []
        schema_enforcement = logic.get("schema_enforcement") or {}

        rows = input_table.to_pylist()
        quarantined: list[dict[str, Any]] = []
        clean: list[dict[str, Any]] = []

        for row in rows:
            out = dict(row)
            reason = self._apply_cleansing(out, cleansing)
            if reason:
                quarantined.append({**out, "_reason": reason})
                continue
            reason = self._apply_standardisation(out, standardisation)
            if reason:
                quarantined.append({**out, "_reason": reason})
                continue
            reason = self._apply_schema_enforcement(out, schema_enforcement)
            if reason:
                quarantined.append({**out, "_reason": reason})
                continue
            clean.append(out)

        # Dedup per business keys (US2-AC3): keep first occurrence.
        if dedup_keys:
            seen: set[tuple[Any, ...]] = set()
            deduped: list[dict[str, Any]] = []
            for row in clean:
                key = tuple(row.get(k) for k in dedup_keys)
                if key in seen:
                    quarantined.append({**row, "_reason": "duplicate business key"})
                    continue
                seen.add(key)
                deduped.append(row)
            clean = deduped

        return TransformationResult(
            table=pa.Table.from_pylist(
                clean, schema=self._output_schema(input_table, schema_enforcement)
            ),
            quarantined=quarantined,
        )

    def _output_schema(
        self, input_table: pa.Table, schema_enforcement: dict[str, dict[str, Any]]
    ) -> pa.Schema:
        """Build the output schema from schema_enforcement + input extras.

        Columns declared in ``schema_enforcement`` use the enforced type
        (reflecting type conversion); columns not declared keep their input
        type.
        """
        fields = []
        declared = set(schema_enforcement)
        for name in input_table.schema.names:
            if name in declared:
                spec = schema_enforcement[name]
                pa_type = _COERCE_TYPES.get(spec.get("type"), input_table.schema.field(name).type)
                fields.append(pa.field(name, pa_type, nullable=bool(spec.get("nullable", True))))
            else:
                field = input_table.schema.field(name)
                fields.append(pa.field(name, field.type, nullable=field.nullable))
        return pa.schema(fields)

    # -- per-row operations ---------------------------------------------------

    def _apply_cleansing(self, row: dict[str, Any], ops: list[dict[str, Any]]) -> str | None:
        """Apply cleansing ops; return a quarantine reason on failure."""
        for op in ops:
            column = op.get("column")
            op_name = op.get("op")
            if column not in row:
                continue
            value = row[column]
            if op_name == "trim":
                if isinstance(value, str):
                    row[column] = value.strip()
            elif op_name == "lower":
                if isinstance(value, str):
                    row[column] = value.lower()
            elif op_name == "upper":
                if isinstance(value, str):
                    row[column] = value.upper()
            elif op_name == "strip_nulls":
                if value is None:
                    row[column] = ""
            elif op_name == "coerce_type":
                target = op.get("to")
                coerced, ok = self._coerce(value, target)
                if not ok:
                    return f"type coercion failed for {column} -> {target}"
                row[column] = coerced
        return None

    def _apply_standardisation(self, row: dict[str, Any], ops: list[dict[str, Any]]) -> str | None:
        """Apply standardisation ops; return a quarantine reason on failure."""
        for op in ops:
            column = op.get("column")
            op_name = op.get("op")
            if column not in row:
                continue
            value = row[column]
            if op_name == "upper" and isinstance(value, str):
                row[column] = value.upper()
            elif op_name == "lower" and isinstance(value, str):
                row[column] = value.lower()
            elif op_name == "trim" and isinstance(value, str):
                row[column] = value.strip()
        return None

    def _apply_schema_enforcement(
        self, row: dict[str, Any], schema: dict[str, dict[str, Any]]
    ) -> str | None:
        """Enforce the output schema; return a quarantine reason on failure."""
        for column, spec in schema.items():
            expected_type = spec.get("type")
            nullable = bool(spec.get("nullable", True))
            value = row.get(column)
            if value is None:
                if not nullable:
                    return f"null value in non-nullable column {column}"
                continue
            if not self._type_matches(value, expected_type):
                return f"type mismatch for {column}: expected {expected_type}"
        return None

    # -- helpers --------------------------------------------------------------

    def _coerce(self, value: Any, target: str | None) -> tuple[Any, bool]:
        """Coerce ``value`` to ``target`` type; return (value, ok)."""
        if value is None:
            return None, True
        if target == "integer":
            try:
                return int(value), True
            except (TypeError, ValueError):
                return value, False
        if target == "float":
            try:
                return float(value), True
            except (TypeError, ValueError):
                return value, False
        if target == "string":
            return str(value), True
        if target == "boolean":
            if isinstance(value, bool):
                return value, True
            if isinstance(value, str):
                lowered = value.strip().lower()
                if lowered in ("true", "1", "yes"):
                    return True, True
                if lowered in ("false", "0", "no"):
                    return False, True
            return value, False
        # Unknown target: leave unchanged (schema enforcement catches it).
        return value, True

    def _type_matches(self, value: Any, expected_type: str) -> bool:
        """Whether ``value`` satisfies the expected schema type."""
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "float":
            return isinstance(value, (int, float)) and not isinstance(value, bool)
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "timestamp":
            return isinstance(value, (int, float))
        if expected_type == "date":
            return isinstance(value, (int, float))
        if expected_type == "binary":
            return isinstance(value, (bytes, bytearray))
        return True


def classify_schema_change(
    previous: dict[str, dict[str, Any]],
    proposed: dict[str, dict[str, Any]],
) -> str:
    """Classify a schema change per contract classification (FR-013).

    Returns ``"additive"`` (new nullable column tolerated), ``"breaking"``
    (type change or column removal), or ``"none"`` (no change).
    """
    previous = previous or {}
    proposed = proposed or {}
    if previous == proposed:
        return "none"
    for column, spec in proposed.items():
        if column not in previous:
            # New column: additive only if nullable.
            if not bool(spec.get("nullable", True)):
                return "breaking"
            continue
        if previous[column].get("type") != spec.get("type"):
            return "breaking"
    for column in previous:
        if column not in proposed:
            return "breaking"
    return "additive"
