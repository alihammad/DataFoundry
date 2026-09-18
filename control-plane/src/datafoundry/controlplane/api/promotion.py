"""API router: promotion (T038, contracts/processing-api.md §3).

- ``GET /datasets/{id}/promotion`` — current state + history with
  gate_report_id + transitioned_at + blocked_reason (US4-AC3).
- ``POST /datasets/{id}/promotion/override`` — override a blocked gate
  (FR-008): 201 active; 422 incomplete; 403 caller lacks override authority
  (attempt recorded); audit ``promotion.overridden``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ForbiddenError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.db.models import (
    Dataset,
    GateReport,
    PromotionStateRow,
)
from datafoundry.controlplane.quality.override import (
    IncompleteOverrideError,
    grant_override,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["promotion"])


# -- request/response models ----------------------------------------------------


class PromotionHistoryItem(BaseModel):
    state: str
    gate_report_id: str | None
    transitioned_at: str | None
    blocked_reason: str | None


class PromotionStatus(BaseModel):
    dataset_id: uuid.UUID
    current_state: str | None
    history: list[PromotionHistoryItem]


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorising_identity: str
    reason: str
    expiry: datetime
    impact_assessment: str


class OverrideResponse(BaseModel):
    override_id: uuid.UUID
    status: str


# -- helpers --------------------------------------------------------------------


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


def _get_blocked_report(session: Session, dataset_id: uuid.UUID) -> GateReport | None:
    """The latest gate report for a dataset's current blocked state."""
    promo = session.execute(
        select(PromotionStateRow).where(PromotionStateRow.dataset_id == dataset_id)
    ).scalar_one_or_none()
    if promo is None or promo.gate_report_id is None:
        return None
    return session.get(GateReport, promo.gate_report_id)


# -- routes ----------------------------------------------------------------------


@router.get("/datasets/{dataset_id}/promotion", response_model=PromotionStatus)
def get_promotion(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> PromotionStatus:
    """Current promotion state + history (US4-AC3)."""
    _get_dataset(session, dataset_id)
    promo = session.execute(
        select(PromotionStateRow).where(PromotionStateRow.dataset_id == dataset_id)
    ).scalar_one_or_none()
    if promo is None:
        return PromotionStatus(dataset_id=dataset_id, current_state=None, history=[])
    return PromotionStatus(
        dataset_id=dataset_id,
        current_state=promo.state.value,
        history=[
            PromotionHistoryItem(
                state=promo.state.value,
                gate_report_id=str(promo.gate_report_id) if promo.gate_report_id else None,
                transitioned_at=(
                    promo.transitioned_at.isoformat() if promo.transitioned_at else None
                ),
                blocked_reason=promo.blocked_reason,
            )
        ],
    )


@router.post(
    "/datasets/{dataset_id}/promotion/override",
    status_code=201,
    response_model=OverrideResponse,
)
def override_blocked_gate(
    dataset_id: uuid.UUID,
    body: OverrideRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> OverrideResponse:
    """Override a blocked gate (FR-008, US5-AC1)."""
    dataset = _get_dataset(session, dataset_id)
    report = _get_blocked_report(session, dataset_id)

    # Override authority: only the dataset owner may grant (US5-AC2).
    if caller.identity != dataset.owner_identity:
        raise ForbiddenError(
            ["override.grant"],
            detail="only the dataset owner may grant an override",
        )

    if report is None:
        raise NotFoundError(f"no blocked gate report for dataset {dataset_id}")

    try:
        override = grant_override(
            session,
            report_id=report.id,
            dataset_id=dataset.id,
            authorising_identity=body.authorising_identity,
            reason=body.reason,
            expiry=body.expiry,
            impact_assessment=body.impact_assessment,
            granted_by=caller.identity,
        )
    except IncompleteOverrideError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "override",
                    "code": "missing_field",
                    "message": str(exc),
                    "remediation": "Provide all required override fields (FR-008)",
                }
            ]
        ) from exc

    AuditService(session).promotion_overridden(
        actor=caller.identity,
        platform_id=None,
        dataset_id=dataset.id,
        override_id=override.id,
    )
    return OverrideResponse(override_id=override.id, status=override.status.value)
