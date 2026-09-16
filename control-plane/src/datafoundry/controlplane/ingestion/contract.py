"""Source contract management (T011).

Contract inference from observed schema (marked ``pending``, never
auto-approved — constitution V, FR-010) and change classification
(breaking / non-breaking / warning per the classification table).
"""

from __future__ import annotations

from typing import Any

from datafoundry.controlplane.db.models import ApprovalStatus, ContractOrigin, SourceContract
from sqlalchemy.orm import Session


def infer_contract(
    session: Session,
    *,
    source_id: str,
    object_name: str,
    schema_definition: dict[str, Any],
    created_by: str,
) -> SourceContract:
    """Infer a contract from observed schema, marked pending (never approved).

    Idempotent per (source_id, object_name): if a contract already exists it is
    returned unchanged.
    """
    existing = (
        session.query(SourceContract)
        .filter_by(source_id=source_id, object_name=object_name)
        .first()
    )
    if existing is not None:
        return existing

    contract = SourceContract(
        source_id=source_id,
        object_name=object_name,
        schema_definition=schema_definition,
        origin=ContractOrigin.inferred,
        approval_status=ApprovalStatus.pending,
        created_by=created_by,
    )
    session.add(contract)
    session.flush()
    return contract


def classify_change(
    *,
    column: str,
    change: str,
    old_type: str | None = None,
    new_type: str | None = None,
) -> dict[str, Any]:
    """Classify a schema change per the classification table.

    Returns ``{"column", "change", "classification", "detail"}``.
    """
    if change == "type_change":
        return {
            "column": column,
            "change": change,
            "classification": "breaking",
            "detail": f"column '{column}' type changed from {old_type} to {new_type}",
        }
    if change == "dropped_column":
        return {
            "column": column,
            "change": change,
            "classification": "breaking",
            "detail": f"column '{column}' dropped from source",
        }
    if change == "added_column":
        return {
            "column": column,
            "change": change,
            "classification": "non_breaking",
            "detail": f"column '{column}' added to source",
        }
    if change == "nullability_tightened":
        return {
            "column": column,
            "change": change,
            "classification": "warning",
            "detail": f"column '{column}' became non-nullable",
        }
    return {
        "column": column,
        "change": change,
        "classification": "warning",
        "detail": f"column '{column}' changed",
    }
