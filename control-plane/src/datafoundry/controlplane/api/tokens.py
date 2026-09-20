"""API router: tokens (T030, contracts/security-api.md §4).

- ``POST /datasets/{id}/tokens/tokenise`` — tokenise a column value
  (FR-011): 200 token; deterministic same-input-same-token; 403 unauthorised.
- ``POST /datasets/{id}/tokens/detokenise`` — detokenise (authorised only,
  FR-012): 200 value + audited; 403 unauthorised + recorded (FR-015).
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db, get_security_gateway
from datafoundry.controlplane.api.errors import (
    ForbiddenError,
    NotFoundError,
)
from datafoundry.controlplane.db.models import (
    AuditResult,
    Classification,
    Dataset,
    ProtectionPolicy,
)
from datafoundry.controlplane.security.audit import record_audit
from datafoundry.controlplane.security.tokens import (
    TokenNotFoundError,
    detokenise,
    tokenise,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["tokens"])


class TokeniseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    value: str
    deterministic: bool = True


class TokeniseResponse(BaseModel):
    token: str


class DetokeniseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str
    token: str
    purpose: str


class DetokeniseResponse(BaseModel):
    value: str


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


def _policy_for_column(
    session: Session, dataset_id: uuid.UUID, column: str
) -> ProtectionPolicy | None:
    """Resolve the protection policy governing a dataset column (FR-002)."""
    classification = session.execute(
        select(Classification).where(
            Classification.dataset_id == dataset_id,
            Classification.column == column,
        )
    ).scalar_one_or_none()
    if classification is None:
        classification = session.execute(
            select(Classification).where(
                Classification.dataset_id == dataset_id,
                Classification.column.is_(None),
            )
        ).scalar_one_or_none()
    if classification is None:
        return None
    return session.get(ProtectionPolicy, classification.policy_id)


@router.post(
    "/datasets/{dataset_id}/tokens/tokenise",
    response_model=TokeniseResponse,
)
def tokenise_endpoint(
    dataset_id: uuid.UUID,
    body: TokeniseRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    security_gateway: Any = Depends(get_security_gateway),
) -> TokeniseResponse:
    """Tokenise a column value (FR-011)."""
    dataset = _get_dataset(session, dataset_id)
    policy = _policy_for_column(session, dataset.id, body.column)
    # Tokenisation requires data-read permission (authorised_roles).
    if policy is not None:
        authorised = list(policy.authorised_roles or [])
        if not set(caller.roles).intersection(authorised):
            raise ForbiddenError(
                ["tokenise"],
                detail="caller lacks tokenisation permission for this column (FR-011)",
            )
    token = tokenise(
        session,
        dataset_id=dataset.id,
        column=body.column,
        value=body.value,
        deterministic=body.deterministic,
        token_service_ref=policy.token_service_ref if policy else "simulated-token-vault",
        gateway=security_gateway,
    )
    record_audit(
        session,
        identity=caller.identity,
        action="security.tokenise",
        result=AuditResult.success,
        dataset_id=dataset.id,
        column=body.column,
    )
    session.flush()
    return TokeniseResponse(token=token)


@router.post(
    "/datasets/{dataset_id}/tokens/detokenise",
    response_model=DetokeniseResponse,
)
def detokenise_endpoint(
    dataset_id: uuid.UUID,
    body: DetokeniseRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    security_gateway: Any = Depends(get_security_gateway),
) -> DetokeniseResponse:
    """Detokenise (authorised only, FR-012)."""
    dataset = _get_dataset(session, dataset_id)
    policy = _policy_for_column(session, dataset.id, body.column)
    detokenise_roles = list(policy.detokenise_roles or []) if policy else []
    if not set(caller.roles).intersection(detokenise_roles):
        # Unauthorised attempt recorded (FR-015). Commit so the record
        # survives the 403 (get_db rolls back on exception).
        record_audit(
            session,
            identity=caller.identity,
            action="security.detokenise",
            result=AuditResult.denied,
            dataset_id=dataset.id,
            column=body.column,
            purpose=body.purpose,
        )
        session.commit()
        raise ForbiddenError(
            ["detokenise"],
            detail="caller lacks detokenisation right for this column (FR-012)",
        )
    try:
        value = detokenise(session, token=body.token, gateway=security_gateway)
    except TokenNotFoundError as exc:
        raise NotFoundError(f"no token {body.token}") from exc
    record_audit(
        session,
        identity=caller.identity,
        action="security.detokenise",
        result=AuditResult.success,
        dataset_id=dataset.id,
        column=body.column,
        purpose=body.purpose,
    )
    session.flush()
    return DetokeniseResponse(value=value)
