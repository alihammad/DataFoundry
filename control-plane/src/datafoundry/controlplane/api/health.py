"""API router: on-demand health re-check (T080, deployment-api.md §4).

``POST /api/v1/platforms/{platform_id}/health-checks`` — 202 + check_id;
results appear via GET platform detail.
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.api.auth import ACTION_UPDATE_PLATFORM, Caller, require_action
from datafoundry.controlplane.api.deps import get_cloud_gateway, get_db
from datafoundry.controlplane.api.errors import NotFoundError
from datafoundry.controlplane.db.models import Platform
from datafoundry.controlplane.health.service import HealthService
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["health"])


class HealthCheckAccepted(BaseModel):
    check_id: uuid.UUID


@router.post(
    "/platforms/{platform_id}/health-checks",
    status_code=202,
    response_model=HealthCheckAccepted,
)
def trigger_health_checks(
    platform_id: uuid.UUID,
    caller: Caller = Depends(require_action(ACTION_UPDATE_PLATFORM)),
    session: Session = Depends(get_db),
    gateway=Depends(get_cloud_gateway),
) -> HealthCheckAccepted:
    platform = session.get(Platform, platform_id)
    if platform is None:
        raise NotFoundError(f"platform {platform_id} not found")

    service = HealthService(session, gateway=gateway)
    outcome = service.run_checks(platform)
    session.flush()
    return HealthCheckAccepted(check_id=outcome.check_id)
