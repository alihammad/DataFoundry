"""API router: overrides (T040, contracts/quality-api.md §5).

- ``POST /reports/{report_id}/override`` — grant an override for a blocked run
  (FR-011, FR-012): 201 active; 422 incomplete; 403 caller lacks override
  authority (attempt recorded, US5-AC2); audit ``override.granted``.
- ``GET /datasets/{dataset_id}/overrides`` — list override audit history
  (FR-012).
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
from datafoundry.controlplane.db.models import Dataset, GateOverride, GateReport
from datafoundry.controlplane.quality.override import (
    IncompleteOverrideError,
    grant_override,
    list_overrides,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

router = APIRouter(tags=["overrides"])


# -- request/response models ----------------------------------------------------


class OverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authorising_identity: str
    reason: str
    expiry: datetime
    impact_assessment: str


class OverrideResponse(BaseModel):
    override_id: uuid.UUID
    status: str


class OverrideItem(BaseModel):
    override_id: uuid.UUID
    report_id: uuid.UUID
    authorising_identity: str
    reason: str
    expiry: datetime
    status: str
    granted_at: datetime


class OverrideListResponse(BaseModel):
    items: list[OverrideItem]


# -- helpers --------------------------------------------------------------------


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


def _get_report(session: Session, report_id: uuid.UUID) -> GateReport:
    report = session.get(GateReport, report_id)
    if report is None:
        raise NotFoundError(f"no gate report with id {report_id}")
    return report


def _item(override: GateOverride) -> OverrideItem:
    return OverrideItem(
        override_id=override.id,
        report_id=override.report_id,
        authorising_identity=override.authorising_identity,
        reason=override.reason,
        expiry=override.expiry,
        status=override.status.value,
        granted_at=override.granted_at,
    )


# -- routes ---------------------------------------------------------------------


@router.post(
    "/reports/{report_id}/override",
    status_code=201,
    response_model=OverrideResponse,
)
def grant_override_endpoint(
    report_id: uuid.UUID,
    body: OverrideRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> OverrideResponse:
    """Grant an override for a blocked run (FR-011, FR-012)."""
    report = _get_report(session, report_id)
    dataset = _get_dataset(session, report.dataset_id)

    # Override authority: only the dataset owner may grant (US5-AC2).
    if caller.identity != dataset.owner_identity:
        raise ForbiddenError(
            ["override.grant"],
            detail="only the dataset owner may grant an override",
        )

    try:
        override = grant_override(
            session,
            report_id=report.id,
            dataset_id=report.dataset_id,
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
                    "remediation": "Provide all required override fields (FR-011)",
                }
            ]
        ) from exc

    AuditService(session).override_granted(
        actor=caller.identity,
        dataset_id=report.dataset_id,
        report_id=report.id,
        override_id=override.id,
        authorising_identity=override.authorising_identity,
        expiry=override.expiry.isoformat(),
    )
    return OverrideResponse(override_id=override.id, status=override.status.value)


@router.get(
    "/datasets/{dataset_id}/overrides",
    response_model=OverrideListResponse,
)
def list_overrides_endpoint(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> OverrideListResponse:
    """List the override audit history for a dataset (FR-012)."""
    _get_dataset(session, dataset_id)
    overrides = list_overrides(session, dataset_id=dataset_id)
    return OverrideListResponse(items=[_item(o) for o in overrides])
