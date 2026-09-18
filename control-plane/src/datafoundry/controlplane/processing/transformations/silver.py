"""Silver transformation (feature 003, T023).

Cleansing, type conversion, standardisation, schema enforcement, dedup per
``dedup_keys``, and malformed-record routing to quarantine (FR-006).
"""

from __future__ import annotations

from typing import Any

import pyarrow as pa
from datafoundry.controlplane.processing.transformations.base import (
    Transformation,
    TransformationResult,
)


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

        Phase 2 stub: passes rows through with dedup applied. Full cleansing
        and schema enforcement land in Phase 4 (T023/T024).
        """
        rows = input_table.to_pylist()
        quarantined: list[dict[str, Any]] = []

        # Dedup per business keys (US2-AC3): keep first occurrence.
        if dedup_keys:
            seen: set[tuple[Any, ...]] = set()
            deduped: list[dict[str, Any]] = []
            for row in rows:
                key = tuple(row.get(k) for k in dedup_keys)
                if key in seen:
                    quarantined.append({**row, "_reason": "duplicate business key"})
                    continue
                seen.add(key)
                deduped.append(row)
            rows = deduped

        return TransformationResult(
            table=pa.Table.from_pylist(rows, schema=input_table.schema),
            quarantined=quarantined,
        )
