"""Pending-approval API router (feature 007, T041/T044, ui-api.md §5).

- ``GET /ui/approvals`` — list pending approvals (aggregates existing approval
  records: production changes, overrides, semantic publications, contracts).
- ``POST /ui/approvals/{approval_id}/decide`` — approve or deny (FR-016).

MVP: the aggregation reads the existing override records (feature 004) as the
canonical approval source; other approval types are added as their features
land.
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
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.ui_schema import ApprovalDecision
from datafoundry.controlplane.db.models import GateOverride, OverrideStatus
from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ui/approvals", tags=["ui-approvals"])

ADMIN_IDENTITY = "dev@datafoundry.local"


@router.get("")
def list_approvals(
    type: str | None = None,
    state: str | None = None,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, list[dict]]:
    stmt = select(GateOverride)
    if state:
        stmt = stmt.where(GateOverride.status == OverrideStatus(state))
    rows = session.execute(stmt).scalars()
    items = []
    for o in rows:
        if type and type != "override":
            continue
        items.append(
            {
                "approval_id": str(o.id),
                "approval_type": "override",
                "requester": o.authorising_identity,
                "payload_ref": str(o.report_id),
                "decision_state": str(o.status),
                "created_at": o.granted_at.isoformat(),
            }
        )
    return {"items": items}


@router.post("/{approval_id}/decide")
def decide_approval(
    approval_id: uuid.UUID,
    body: ApprovalDecision,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    if caller.identity != ADMIN_IDENTITY:
        raise ForbiddenError(["ui.approval.decide"])
    try:
        body = ApprovalDecision.model_validate(body.model_dump())
    except ValidationError as exc:
        errors = [
            {"path": ".".join(str(p) for p in e["loc"]), "code": e["type"], "message": e["msg"]}
            for e in exc.errors()
        ]
        raise ConfigValidationError(errors) from exc

    override = session.get(GateOverride, approval_id)
    if override is None:
        raise NotFoundError("approval not found")
    override.status = (
        OverrideStatus.active if body.decision == "approved" else OverrideStatus.revoked
    )
    session.flush()
    AuditService(session).ui_approval_decided(
        actor=caller.identity,
        approval_id=str(override.id),
        approval_type="override",
        decision=body.decision,
    )
    return {"approval_id": str(override.id), "decision_state": str(override.status)}
