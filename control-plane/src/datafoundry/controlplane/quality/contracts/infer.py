"""Contract inference (T024, R-04, FR-007).

Where no explicit contract exists, the first successful ingestion infers a
contract from the observed schema and marks it ``pending`` approval. Inference
is deterministic (observed schema -> pending approval) and never auto-approved
(constitution V, FR-007). Only after approval does the contract gate promotion.
"""

from __future__ import annotations

from typing import Any

from datafoundry.controlplane.db.models import ApprovalStatus, ContractOrigin


def infer_schema_definition(observed_schema: dict[str, Any]) -> dict[str, Any]:
    """Build a contract schema definition from an observed schema.

    ``observed_schema`` is ``{column: {type, nullable}}`` (the shape produced
    from a PyArrow table). The inferred contract preserves each column's type
    and nullability.
    """
    definition: dict[str, Any] = {}
    for column, spec in observed_schema.items():
        definition[column] = {
            "type": spec.get("type"),
            "nullable": bool(spec.get("nullable", False)),
        }
    return definition


def infer_contract(
    observed_schema: dict[str, Any],
    *,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Infer a pending DataContract from an observed schema (FR-007).

    Returns the field values for a new :class:`DataContract` row:
    ``origin=inferred``, ``approval_status=pending`` (never auto-approved).
    """
    return {
        "schema_definition": infer_schema_definition(observed_schema),
        "origin": ContractOrigin.inferred,
        "approval_status": ApprovalStatus.pending,
        "created_by": created_by,
    }


__all__ = ["infer_contract", "infer_schema_definition"]
