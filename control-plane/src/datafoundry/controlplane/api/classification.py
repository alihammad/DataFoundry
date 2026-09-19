"""API router: classification (T020, contracts/security-api.md §1).

- ``POST /datasets/{id}/classification`` — set a dataset/column classification
  (FR-001): 201 with classification_id/level/policy_id; 422 invalid level /
  unknown policy; 403 unauthorised downgrade (FR-020).
- ``GET /datasets/{id}/classification`` — level + per-column protection
  metadata, never key material (FR-017, SC-003).
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ForbiddenError,
    NotFoundError,
)
from datafoundry.controlplane.db.models import (
    Classification,
    Dataset,
    ProtectionPolicy,
    SecurityLevel,
)
from datafoundry.controlplane.security.classification import (
    get_classification,
    is_downgrade,
    set_classification,
)
from datafoundry.controlplane.security.policy import PolicyNotFoundError, get_policy
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["classification"])


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: str
    column: str | None = None
    policy_id: uuid.UUID


class ClassificationResponse(BaseModel):
    classification_id: uuid.UUID
    level: str
    policy_id: uuid.UUID


class ColumnProtection(BaseModel):
    column: str
    mechanism: str
    masking_status: str | None
    authorised_roles: list[str]
    key_ref_id: str | None


class ClassificationDetail(BaseModel):
    dataset_id: uuid.UUID
    level: str
    policy_id: uuid.UUID
    columns: list[ColumnProtection]


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


@router.post(
    "/datasets/{dataset_id}/classification",
    status_code=201,
    response_model=ClassificationResponse,
)
def set_dataset_classification(
    dataset_id: uuid.UUID,
    body: ClassificationRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ClassificationResponse:
    """Set a dataset/column classification (FR-001, FR-020)."""
    dataset = _get_dataset(session, dataset_id)
    try:
        level = SecurityLevel(body.level)
    except ValueError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "level",
                    "code": "invalid_value",
                    "message": f"invalid classification level '{body.level}'",
                    "remediation": (
                        "Use one of public/internal/confidential/restricted/highly_restricted"
                    ),
                }
            ]
        ) from exc
    try:
        policy = get_policy(session, policy_id=body.policy_id)
    except PolicyNotFoundError as exc:
        raise NotFoundError(f"no protection policy with id {body.policy_id}") from exc

    # Downgrade authorisation (FR-020): only the dataset owner may downgrade.
    current = get_classification(session, dataset_id=dataset.id, column=body.column)
    if (
        current is not None
        and is_downgrade(current.level, level)
        and caller.identity != dataset.owner_identity
    ):
        raise ForbiddenError(
            ["classification.downgrade"],
            detail="only the dataset owner may downgrade a classification (FR-020)",
        )

    row = set_classification(
        session,
        dataset_id=dataset.id,
        level=level,
        policy_id=policy.id,
        changed_by=caller.identity,
        column=body.column,
    )
    session.flush()
    return ClassificationResponse(
        classification_id=row.id, level=row.level.value, policy_id=row.policy_id
    )


@router.get("/datasets/{dataset_id}/classification", response_model=ClassificationDetail)
def get_dataset_classification(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ClassificationDetail:
    """Classification + per-column protection metadata (FR-017)."""
    dataset = _get_dataset(session, dataset_id)
    rows = session.execute(
        select(Classification).where(Classification.dataset_id == dataset.id)
    ).scalars()
    dataset_level = None
    dataset_policy = None
    columns: list[ColumnProtection] = []
    for row in rows:
        policy = session.get(ProtectionPolicy, row.policy_id)
        if row.column is None:
            dataset_level = row.level.value
            dataset_policy = row.policy_id
        else:
            columns.append(
                ColumnProtection(
                    column=row.column,
                    mechanism=policy.mechanism.value if policy else "none",
                    masking_status=(
                        "masked" if policy and policy.mechanism.value == "mask" else None
                    ),
                    authorised_roles=list(policy.authorised_roles or []) if policy else [],
                    key_ref_id=str(policy.key_ref_id) if policy and policy.key_ref_id else None,
                )
            )
    return ClassificationDetail(
        dataset_id=dataset.id,
        level=dataset_level or "unclassified",
        policy_id=dataset_policy or uuid.UUID(int=0),
        columns=columns,
    )
