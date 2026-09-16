"""Ingestion validation (T010).

File validation (exists, readable, format, encoding, checksum — FR-006),
schema/contract compatibility (FR-009/FR-010), and record-count reconciliation
(FR-009).
"""

from __future__ import annotations

import hashlib
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

#: Supported file formats (FR-001).
SUPPORTED_FORMATS = frozenset({"csv", "json", "parquet"})


def validate_file(
    *,
    content: bytes,
    file_name: str,
    declared_format: str | None = None,
    declared_checksum: str | None = None,
) -> dict[str, Any]:
    """Validate a file before ingestion (FR-006).

    Returns ``{"ok": True}`` or ``{"ok": False, "reason", "failed_check"}``.
    Checks: readable, format, encoding, checksum (where provided).
    """
    if not content:
        return {"ok": False, "reason": "file is empty", "failed_check": "readability"}

    fmt = (declared_format or _guess_format(file_name)).lower()
    if fmt not in SUPPORTED_FORMATS:
        return {
            "ok": False,
            "reason": f"unsupported format '{fmt}'",
            "failed_check": "format",
        }

    # Format/encoding validation.
    try:
        _parse_content(content, fmt)
    except Exception as exc:
        return {
            "ok": False,
            "reason": f"file failed {fmt} validation: {exc}",
            "failed_check": "format",
        }

    # Checksum (FR-007): identical checksum = duplicate delivery.
    if declared_checksum:
        actual = hashlib.sha256(content).hexdigest()
        if actual != declared_checksum:
            return {
                "ok": False,
                "reason": "checksum mismatch",
                "failed_check": "checksum",
            }

    return {"ok": True}


def _guess_format(file_name: str) -> str:
    if file_name.endswith(".csv"):
        return "csv"
    if file_name.endswith(".json"):
        return "json"
    if file_name.endswith(".parquet"):
        return "parquet"
    return "unknown"


def _parse_content(content: bytes, fmt: str) -> None:
    """Parse content to confirm it is a valid file of the given format."""
    if fmt == "parquet":
        pq.read_table(pa.BufferReader(content))
    elif fmt == "json":
        import json

        json.loads(content.decode("utf-8"))
    elif fmt == "csv":
        import csv
        import io

        list(csv.reader(io.StringIO(content.decode("utf-8"))))


def validate_contract_compat(
    expected: dict[str, Any], observed: dict[str, Any]
) -> list[dict[str, Any]]:
    """Compare observed schema against a recorded contract.

    Returns a list of change records, each with ``column``, ``change``,
    ``classification`` (breaking / non_breaking / warning), and ``detail``.
    """
    violations: list[dict[str, Any]] = []
    for column, observed_spec in observed.items():
        expected_spec = expected.get(column)
        if expected_spec is None:
            violations.append(
                {
                    "column": column,
                    "change": "added_column",
                    "classification": "non_breaking",
                    "detail": f"column '{column}' added to source",
                }
            )
            continue
        if observed_spec.get("type") != expected_spec.get("type"):
            violations.append(
                {
                    "column": column,
                    "change": "type_change",
                    "classification": "breaking",
                    "detail": (
                        f"column '{column}' type changed from "
                        f"{expected_spec.get('type')} to {observed_spec.get('type')}"
                    ),
                }
            )
        elif observed_spec.get("nullable") is False and expected_spec.get("nullable") is True:
            violations.append(
                {
                    "column": column,
                    "change": "nullability_tightened",
                    "classification": "warning",
                    "detail": f"column '{column}' became non-nullable",
                }
            )
    for column in expected:
        if column not in observed:
            violations.append(
                {
                    "column": column,
                    "change": "dropped_column",
                    "classification": "breaking",
                    "detail": f"column '{column}' dropped from source",
                }
            )
    return violations


def reconcile_record_count(
    *,
    source_count: int,
    ingested_count: int,
    tolerance: int = 0,
) -> dict[str, Any]:
    """Record-count reconciliation (FR-009, US3-AC4).

    Returns ``{"ok": True}`` or ``{"ok": False, "difference", "reason"}``.
    """
    difference = abs(source_count - ingested_count)
    if difference > tolerance:
        return {
            "ok": False,
            "difference": difference,
            "reason": (
                f"reconciliation failed: source count {source_count} vs "
                f"ingested count {ingested_count} (difference {difference} > "
                f"tolerance {tolerance})"
            ),
        }
    return {"ok": True, "difference": difference}
