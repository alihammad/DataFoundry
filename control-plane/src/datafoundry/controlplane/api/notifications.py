"""Notification-channel API router (feature 007, T019/T045, ui-api.md §3).

- ``POST /ui/notifications`` — configure a channel (FR-014): 201; 422 invalid/secret-scan.
- ``GET /ui/notifications?platform_id=`` — list channels (config never returned, FR-022).
- ``PUT /ui/notifications/{channel_id}`` — update a channel (FR-017 concurrency).
- ``DELETE /ui/notifications/{channel_id}`` — remove a channel.
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.ui_schema import (
    NotificationChannelCreate,
    NotificationChannelUpdate,
)
from datafoundry.controlplane.db.models import NotificationChannel
from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ui/notifications", tags=["ui-notifications"])


@router.post("", status_code=201)
def create_channel(
    body: NotificationChannelCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        body = NotificationChannelCreate.model_validate(body.model_dump())
    except ValidationError as exc:
        errors = [
            {"path": ".".join(str(p) for p in e["loc"]), "code": e["type"], "message": e["msg"]}
            for e in exc.errors()
        ]
        raise ConfigValidationError(errors) from exc

    channel = NotificationChannel(
        platform_id=uuid.UUID(body.platform_id),
        channel_type=body.channel_type,
        name=body.name,
        config=body.config,
        event_types=body.event_types,
        enabled=body.enabled,
        created_by=caller.identity,
    )
    session.add(channel)
    session.flush()
    AuditService(session).ui_notification_configured(
        actor=caller.identity,
        channel_id=channel.id,
        platform_id=channel.platform_id,
        channel_type=str(channel.channel_type),
        name=channel.name,
    )
    return {"channel_id": str(channel.id)}


@router.get("")
def list_channels(
    platform_id: str | None = None,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, list[dict]]:
    stmt = select(NotificationChannel)
    if platform_id:
        stmt = stmt.where(NotificationChannel.platform_id == uuid.UUID(platform_id))
    rows = session.execute(stmt).scalars()
    # Config is never returned (FR-022, SC-006).
    return {
        "items": [
            {
                "channel_id": str(c.id),
                "platform_id": str(c.platform_id),
                "channel_type": str(c.channel_type),
                "name": c.name,
                "event_types": c.event_types,
                "enabled": c.enabled,
            }
            for c in rows
        ]
    }


@router.put("/{channel_id}")
def update_channel(
    channel_id: uuid.UUID,
    body: NotificationChannelUpdate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    channel = session.get(NotificationChannel, channel_id)
    if channel is None:
        raise NotFoundError("notification channel not found")
    try:
        body = NotificationChannelUpdate.model_validate(body.model_dump(exclude_unset=True))
    except ValidationError as exc:
        errors = [
            {"path": ".".join(str(p) for p in e["loc"]), "code": e["type"], "message": e["msg"]}
            for e in exc.errors()
        ]
        raise ConfigValidationError(errors) from exc

    if body.name is not None:
        channel.name = body.name
    if body.config is not None:
        channel.config = body.config
    if body.event_types is not None:
        channel.event_types = body.event_types
    if body.enabled is not None:
        channel.enabled = body.enabled
    session.flush()
    AuditService(session).ui_notification_configured(
        actor=caller.identity,
        channel_id=channel.id,
        platform_id=channel.platform_id,
        channel_type=str(channel.channel_type),
        name=channel.name,
    )
    return {"channel_id": str(channel.id), "updated_at": channel.updated_at.isoformat()}


@router.delete("/{channel_id}", status_code=204)
def delete_channel(
    channel_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> None:
    channel = session.get(NotificationChannel, channel_id)
    if channel is None:
        raise NotFoundError("notification channel not found")
    session.delete(channel)
    session.flush()
