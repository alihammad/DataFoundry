"""API router: data contracts (T025, contracts/quality-api.md §3).

- ``POST /datasets/{dataset_id}/contracts/register`` — register an explicit
  contract (FR-006, US2-AC1): approved immediately; 422 on invalid schema.
- ``POST /datasets/{dataset_id}/contracts/infer`` — infer a contract from the
  observed schema (FR-007, US2-AC3): ``pending``, never auto-approved.
- ``POST /contracts/{contract_id}/approve`` — approve an inferred contract
  (FR-007, US2-AC4): owner authorisation; only then does it gate promotion.
- ``GET /datasets/{dataset_id}/contracts`` — list contracts + violations.
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ForbiddenError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.db.models import (
    ApprovalStatus,
    ContractOrigin,
    ContractViolation,
    DataContract,
    Dataset,
)
from datafoundry.controlplane.quality.contracts.infer import infer_contract
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["contracts"])

#: Allowed column types per contract-schema.md.
ALLOWED_COLUMN_TYPES = {
    "integer",
    "string",
    "float",
    "boolean",
    "timestamp",
    "date",
    "decimal",
    "json",
    "binary",
}


# -- request/response models -----------------------------------------------------


class ContractRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_definition: dict[str, Any]


class ContractRegisterResponse(BaseModel):
    contract_id: uuid.UUID
    version: int
    origin: str
    approval_status: str | None = None


class ContractApproveResponse(BaseModel):
    approval_status: str


class ViolationItem(BaseModel):
    classification: str
    change_description: str
    action_taken: str


class ContractItem(BaseModel):
    contract_id: uuid.UUID
    version: int
    origin: str
    approval_status: str
    violations: list[ViolationItem]


class ContractsListResponse(BaseModel):
    items: list[ContractItem]


# -- helpers ---------------------------------------------------------------------


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


def _get_contract(session: Session, contract_id: uuid.UUID) -> DataContract:
    contract = session.get(DataContract, contract_id)
    if contract is None:
        raise NotFoundError(f"no data contract with id {contract_id}")
    return contract


def _validate_schema_definition(schema_definition: dict[str, Any]) -> None:
    """Validate a contract schema definition (contract-schema.md)."""
    errors: list[dict[str, str]] = []
    if not isinstance(schema_definition, dict) or not schema_definition:
        errors.append(
            {
                "path": "schema_definition",
                "code": "invalid_value",
                "message": "schema_definition must be a non-empty mapping",
                "remediation": "Provide {column: {type, nullable}}",
            }
        )
        raise ConfigValidationError(errors)
    for column, spec in schema_definition.items():
        if not isinstance(spec, dict):
            errors.append(
                {
                    "path": f"schema_definition.{column}",
                    "code": "invalid_value",
                    "message": f"column '{column}' spec must be a mapping",
                    "remediation": "Provide {type, nullable}",
                }
            )
            continue
        col_type = spec.get("type")
        if col_type not in ALLOWED_COLUMN_TYPES:
            errors.append(
                {
                    "path": f"schema_definition.{column}.type",
                    "code": "invalid_value",
                    "message": (
                        f"column '{column}' type '{col_type}' not allowed; "
                        f"use one of {sorted(ALLOWED_COLUMN_TYPES)}"
                    ),
                    "remediation": "Use an allowed column type",
                }
            )
        if "nullable" in spec and not isinstance(spec["nullable"], bool):
            errors.append(
                {
                    "path": f"schema_definition.{column}.nullable",
                    "code": "invalid_value",
                    "message": f"column '{column}' nullable must be a boolean",
                    "remediation": "Use true/false",
                }
            )
    if errors:
        raise ConfigValidationError(errors)


def _next_version(session: Session, dataset_id: uuid.UUID) -> int:
    latest = session.execute(
        select(DataContract.version)
        .where(DataContract.dataset_id == dataset_id)
        .order_by(DataContract.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    return (latest or 0) + 1


# -- routes ----------------------------------------------------------------------


@router.post(
    "/datasets/{dataset_id}/contracts/register",
    status_code=201,
    response_model=ContractRegisterResponse,
)
def register_contract(
    dataset_id: uuid.UUID,
    body: ContractRegisterRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ContractRegisterResponse:
    """Register an explicit contract (FR-006, US2-AC1): approved immediately."""
    _get_dataset(session, dataset_id)
    _validate_schema_definition(body.schema_definition)

    contract = DataContract(
        dataset_id=dataset_id,
        version=_next_version(session, dataset_id),
        schema_definition=body.schema_definition,
        origin=ContractOrigin.explicit,
        approval_status=ApprovalStatus.approved,
        created_by=caller.identity,
        approved_by=caller.identity,
    )
    session.add(contract)
    session.flush()

    AuditService(session).contract_registered(
        actor=caller.identity,
        dataset_id=dataset_id,
        contract_id=contract.id,
        version=contract.version,
        origin=contract.origin.value,
    )
    return ContractRegisterResponse(
        contract_id=contract.id,
        version=contract.version,
        origin=contract.origin.value,
        approval_status=contract.approval_status.value,
    )


@router.post(
    "/datasets/{dataset_id}/contracts/infer",
    status_code=201,
    response_model=ContractRegisterResponse,
)
def infer_contract_endpoint(
    dataset_id: uuid.UUID,
    body: ContractRegisterRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ContractRegisterResponse:
    """Infer a contract from the observed schema (FR-007, US2-AC3): pending."""
    _get_dataset(session, dataset_id)
    _validate_schema_definition(body.schema_definition)

    inferred = infer_contract(body.schema_definition, created_by=caller.identity)
    contract = DataContract(
        dataset_id=dataset_id,
        version=_next_version(session, dataset_id),
        schema_definition=inferred["schema_definition"],
        origin=inferred["origin"],
        approval_status=inferred["approval_status"],
        created_by=caller.identity,
    )
    session.add(contract)
    session.flush()

    AuditService(session).contract_inferred(
        actor=caller.identity,
        dataset_id=dataset_id,
        contract_id=contract.id,
        version=contract.version,
    )
    return ContractRegisterResponse(
        contract_id=contract.id,
        version=contract.version,
        origin=contract.origin.value,
        approval_status=contract.approval_status.value,
    )


@router.post(
    "/contracts/{contract_id}/approve",
    response_model=ContractApproveResponse,
)
def approve_contract(
    contract_id: uuid.UUID,
    body: dict[str, Any] | None = None,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ContractApproveResponse:
    """Approve (or reject) an inferred contract (FR-007, US2-AC4).

    Only the dataset owner may approve. Only after approval does the contract
    gate promotion.
    """
    contract = _get_contract(session, contract_id)
    dataset = _get_dataset(session, contract.dataset_id)

    # Owner authorisation (US2-AC4).
    if caller.identity != dataset.owner_identity:
        raise ForbiddenError(
            ["contract.approve"],
            detail="only the dataset owner may approve a contract",
        )

    action = (body or {}).get("action", "approve")
    if action == "reject":
        contract.approval_status = ApprovalStatus.rejected
    else:
        contract.approval_status = ApprovalStatus.approved
    contract.approved_by = caller.identity
    session.flush()

    AuditService(session).contract_approved(
        actor=caller.identity,
        dataset_id=contract.dataset_id,
        contract_id=contract.id,
        version=contract.version,
        approval_status=contract.approval_status.value,
    )
    return ContractApproveResponse(approval_status=contract.approval_status.value)


@router.get(
    "/datasets/{dataset_id}/contracts",
    response_model=ContractsListResponse,
)
def list_contracts(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ContractsListResponse:
    """List contracts + violations for a dataset (FR-006)."""
    _get_dataset(session, dataset_id)
    contracts = session.execute(
        select(DataContract)
        .where(DataContract.dataset_id == dataset_id)
        .order_by(DataContract.version.desc())
    ).scalars()

    items = []
    for contract in contracts:
        violations = session.execute(
            select(ContractViolation).where(ContractViolation.contract_id == contract.id)
        ).scalars()
        items.append(
            ContractItem(
                contract_id=contract.id,
                version=contract.version,
                origin=contract.origin.value,
                approval_status=contract.approval_status.value,
                violations=[
                    ViolationItem(
                        classification=v.classification.value,
                        change_description=v.change_description,
                        action_taken=v.action_taken,
                    )
                    for v in violations
                ],
            )
        )
    return ContractsListResponse(items=items)
