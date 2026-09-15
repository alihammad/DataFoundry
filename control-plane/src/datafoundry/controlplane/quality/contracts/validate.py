"""Contract validation (T023, R-04, FR-006).

Compares an observed schema against a recorded contract and classifies each
difference per the contract-schema.md classification table:

| Change | Classification | Action |
|---|---|---|
| Column type change | breaking | blocks promotion |
| Column removed | breaking | blocks promotion |
| Additive nullable column | non_breaking | allowed, recorded |
| Additive non-nullable column | breaking | blocks promotion |
| Nullability relaxed (nullable->non-nullable) | breaking | blocks promotion |
| Nullability tightened (non-nullable->nullable) | non_breaking | allowed, recorded |
| Other observed deviation | warning | recorded, notified |

``breaking`` violations block promotion (FR-006, SC-007).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datafoundry.controlplane.db.models import ViolationClassification


@dataclass(frozen=True)
class ContractViolationResult:
    """One classified deviation from a contract."""

    change_description: str
    classification: ViolationClassification
    action_taken: str

    @property
    def blocks(self) -> bool:
        return self.classification == ViolationClassification.breaking


def classify_change(
    *,
    column: str,
    change_type: str,
    observed_type: str | None = None,
    contract_type: str | None = None,
    observed_nullable: bool | None = None,
    contract_nullable: bool | None = None,
) -> ContractViolationResult:
    """Classify a single schema difference per the contract table (FR-006).

    ``change_type`` is one of ``type_change``, ``column_removed``,
    ``column_added``, ``nullability_change``, ``other``.
    """
    if change_type == "type_change":
        return ContractViolationResult(
            change_description=(f"column '{column}' type {contract_type}->{observed_type}"),
            classification=ViolationClassification.breaking,
            action_taken="blocked",
        )
    if change_type == "column_removed":
        return ContractViolationResult(
            change_description=f"column '{column}' removed",
            classification=ViolationClassification.breaking,
            action_taken="blocked",
        )
    if change_type == "column_added":
        if observed_nullable:
            return ContractViolationResult(
                change_description=f"additive nullable column '{column}'",
                classification=ViolationClassification.non_breaking,
                action_taken="allowed+recorded",
            )
        return ContractViolationResult(
            change_description=f"additive non-nullable column '{column}'",
            classification=ViolationClassification.breaking,
            action_taken="blocked",
        )
    if change_type == "nullability_change":
        # contract_nullable -> observed_nullable.
        if contract_nullable and not observed_nullable:
            # Nullability relaxed (nullable -> non-nullable): breaking.
            return ContractViolationResult(
                change_description=(
                    f"column '{column}' nullability relaxed (nullable->non-nullable)"
                ),
                classification=ViolationClassification.breaking,
                action_taken="blocked",
            )
        # Nullability tightened (non-nullable -> nullable): non-breaking.
        return ContractViolationResult(
            change_description=(
                f"column '{column}' nullability tightened (non-nullable->nullable)"
            ),
            classification=ViolationClassification.non_breaking,
            action_taken="allowed+recorded",
        )
    return ContractViolationResult(
        change_description=f"column '{column}': {change_type}",
        classification=ViolationClassification.warning,
        action_taken="notified",
    )


def validate_contract(
    contract_schema: dict[str, Any],
    observed_schema: dict[str, Any],
) -> list[ContractViolationResult]:
    """Compare observed schema against the contract; return classified changes.

    ``contract_schema`` and ``observed_schema`` are ``{column: {type, nullable}}``
    maps (the DataContract.schema_definition shape).
    """
    violations: list[ContractViolationResult] = []
    contract_columns = set(contract_schema)
    observed_columns = set(observed_schema)

    # Columns in the contract but missing from the observed schema: removed.
    for column in sorted(contract_columns - observed_columns):
        violations.append(classify_change(column=column, change_type="column_removed"))

    # Columns in the observed schema but not the contract: added.
    for column in sorted(observed_columns - contract_columns):
        observed = observed_schema[column]
        violations.append(
            classify_change(
                column=column,
                change_type="column_added",
                observed_nullable=observed.get("nullable", False),
            )
        )

    # Columns present in both: type + nullability changes.
    for column in sorted(contract_columns & observed_columns):
        contract = contract_schema[column]
        observed = observed_schema[column]
        contract_type = contract.get("type")
        observed_type = observed.get("type")
        if contract_type and observed_type and contract_type != observed_type:
            violations.append(
                classify_change(
                    column=column,
                    change_type="type_change",
                    observed_type=observed_type,
                    contract_type=contract_type,
                )
            )
            continue
        contract_nullable = contract.get("nullable", False)
        observed_nullable = observed.get("nullable", False)
        if contract_nullable != observed_nullable:
            violations.append(
                classify_change(
                    column=column,
                    change_type="nullability_change",
                    contract_nullable=contract_nullable,
                    observed_nullable=observed_nullable,
                )
            )

    return violations


def has_breaking_change(violations: list[ContractViolationResult]) -> bool:
    """True when any violation blocks promotion (FR-006)."""
    return any(v.blocks for v in violations)


__all__ = [
    "ContractViolationResult",
    "classify_change",
    "has_breaking_change",
    "validate_contract",
]
