"""API router: platforms (T035).

``POST /api/v1/platforms`` — the "one click" (FR-001): validate (all errors
at once) -> register Platform + PlatformConfigVersion -> queue run -> 202.
422/409/403 paths per contracts/deployment-api.md §1; Idempotency-Key
replay returns the original run; every mutation writes an AuditRecord
(FR-014).

``GET /api/v1/platforms`` — cursor pagination over PlatformSummary.
"""

from __future__ import annotations

import base64
import uuid
from typing import Any

from datafoundry.controlplane.api.auth import (
    ACTION_CREATE_PLATFORM,
    ACTION_READ_PLATFORM,
    Caller,
    require_action,
)
from datafoundry.controlplane.api.deps import get_db, get_dispatcher, get_settings_from_app
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ConflictError,
    ForbiddenError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.capabilities.registry import default_registry
from datafoundry.controlplane.config.settings import Settings
from datafoundry.controlplane.config.validation import (
    config_hash,
    validate_platform_config,
)
from datafoundry.controlplane.db.models import (
    DeploymentRun,
    Platform,
)
from datafoundry.controlplane.engine.orchestrator import (
    ActiveRunError,
    Orchestrator,
    has_active_run,
    lock_platform_for_update,
)
from datafoundry.controlplane.providers.base import default_providers
from datafoundry.controlplane.providers.permissions import PermissionChecker
from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["platforms"])


# -- request/response models -----------------------------------------------------


class PlatformDeployRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]
    approval_ref: str | None = None


class PlatformDeployAccepted(BaseModel):
    platform_id: uuid.UUID
    run_id: uuid.UUID
    status: str


class PlatformSummary(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    region: str
    environment_type: str
    status: str
    owner: str
    created_at: str


class PlatformList(BaseModel):
    items: list[PlatformSummary]
    next_cursor: str | None = None


# -- helpers ------------------------------------------------------------------------


def _existing_names(session: Session) -> dict[str, set[str]]:
    """Registered names per ``provider:cloud_scope_id`` (uniqueness rule 8)."""
    stmt = select(Platform.provider, Platform.cloud_scope_id, Platform.name)
    names: dict[str, set[str]] = {}
    for provider, scope, name in session.execute(stmt):
        provider_value = provider.value if hasattr(provider, "value") else str(provider)
        names.setdefault(f"{provider_value}:{scope}", set()).add(name)
    return names


def _encode_cursor(platform_id: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(platform_id.bytes).decode()


def _decode_cursor(cursor: str) -> uuid.UUID:
    return uuid.UUID(bytes=base64.urlsafe_b64decode(cursor.encode()))


# -- POST /platforms -------------------------------------------------------------------


@router.post(
    "/platforms",
    status_code=202,
    response_model=PlatformDeployAccepted,
)
def deploy_platform(
    body: PlatformDeployRequest,
    caller: Caller = Depends(require_action(ACTION_CREATE_PLATFORM)),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_app),
    dispatch=Depends(get_dispatcher),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PlatformDeployAccepted:
    # Idempotency-Key replay: return the original run (cross-cutting rule).
    if idempotency_key:
        existing = session.execute(
            select(DeploymentRun).where(DeploymentRun.idempotency_key == idempotency_key)
        ).scalar_one_or_none()
        if existing is not None:
            return PlatformDeployAccepted(
                platform_id=existing.platform_id,
                run_id=existing.id,
                status=existing.status.value,
            )

    # Permission pre-check (FR-018 fail-fast) — 403 with precise missing list.
    provider_hint = _provider_hint(body.config)
    if provider_hint is not None:
        adapter = default_providers.get(provider_hint)
        checker = PermissionChecker(
            auth_mode=settings.auth_mode, dev_identity=settings.dev_identity
        )
        probe = checker.check(adapter, ACTION_CREATE_PLATFORM)
        if probe.unauthenticated or not probe.authorised:
            raise ForbiddenError(list(probe.missing) or ["valid cloud credentials"])

    # Stage-1 validation: ALL errors at once (FR-003, SC-004).
    result = validate_platform_config(
        body.config,
        providers=default_providers,
        registry=default_registry,
        existing_names=_existing_names(session),
        cloud_scope_id=_cloud_scope_id(settings, provider_hint),
    )
    if not result.valid:
        codes = {e.code for e in result.errors}
        # Duplicate name surfaces as 409 name_taken per contract (FR-013).
        if "name_taken" in codes:
            error = next(e for e in result.errors if e.code == "name_taken")
            raise ConflictError(
                "name_taken",
                error.message,
                scope=f"{provider_hint}/{_cloud_scope_id(settings, provider_hint)}",
            )
        raise ConfigValidationError(result.error_dicts())
    config = result.config
    assert config is not None

    # Production requires approval_ref (FR-010) — request-level field.
    if config.is_production and not (
        body.approval_ref or (config.approval and config.approval.ref)
    ):
        raise ConfigValidationError(
            [
                {
                    "path": "approval_ref",
                    "code": "approval_required",
                    "message": "production deployments require approval_ref (FR-010)",
                    "remediation": "Pass approval_ref in the request body or config approval block",
                }
            ]
        )

    orchestrator = Orchestrator(session, registry=default_registry)
    audit = AuditService(session)

    # One active run per platform + name uniqueness race guard (R-12).
    platform, config_version = orchestrator.register_platform(
        config=config,
        raw_config=body.config,
        owner_identity=caller.identity,
        cloud_scope_id=_cloud_scope_id(settings, provider_hint),
    )
    lock_platform_for_update(session, platform.id)
    if has_active_run(session, platform.id):  # pragma: no cover - fresh platform
        raise ConflictError("active_run", "platform already has an active run")

    try:
        run = orchestrator.queue_run(
            platform=platform,
            config=config,
            config_version=config_version,
            initiated_by=caller.identity,
            approval_ref=body.approval_ref or (config.approval.ref if config.approval else None),
            idempotency_key=idempotency_key,
        )
    except ActiveRunError as exc:
        raise ConflictError("active_run", str(exc)) from exc

    audit.deploy_requested(
        actor=caller.identity,
        platform_id=platform.id,
        run_id=run.id,
        config_version=config_version.version,
        config_hash=config_hash(body.config),
    )
    session.flush()
    dispatch(run.id)
    return PlatformDeployAccepted(platform_id=platform.id, run_id=run.id, status=run.status.value)


def _provider_hint(raw_config: dict[str, Any]) -> str | None:
    platform = raw_config.get("platform")
    if isinstance(platform, dict):
        provider = platform.get("provider")
        if isinstance(provider, str) and provider in ("aws", "gcp"):
            return provider
    return None


def _cloud_scope_id(settings: Settings, provider: str | None) -> str:
    """Cloud scope for uniqueness (FR-013): dev mode uses a fixed local scope;
    cloud_iam mode derives it from the probed caller identity (account id /
    project id — R-12)."""
    if settings.auth_mode == "dev":
        return "dev-local"
    if provider == "aws":
        adapter = default_providers.get("aws")
    elif provider == "gcp":
        adapter = default_providers.get("gcp")
    else:
        return "unknown-scope"
    try:
        identity = adapter.probe_credentials()
    except Exception:
        return "unknown-scope"
    return adapter.cloud_scope_id(identity)


# -- GET /platforms ---------------------------------------------------------------------


@router.get(
    "/platforms",
    response_model=PlatformList,
    dependencies=[Depends(require_action(ACTION_READ_PLATFORM))],
)
def list_platforms(
    cursor: str | None = None,
    limit: int = 20,
    session: Session = Depends(get_db),
) -> PlatformList:
    limit = max(1, min(limit, 100))
    stmt = select(Platform).order_by(Platform.created_at, Platform.id)
    if cursor:
        after_id = _decode_cursor(cursor)
        after = session.get(Platform, after_id)
        if after is not None:
            stmt = stmt.where((Platform.created_at, Platform.id) > (after.created_at, after.id))
    platforms = list(session.execute(stmt.limit(limit + 1)).scalars())
    next_cursor = _encode_cursor(platforms[limit - 1].id) if len(platforms) > limit else None
    items = [
        PlatformSummary(
            id=p.id,
            name=p.name,
            provider=p.provider.value,
            region=p.region,
            environment_type=p.environment_type.value,
            status=p.status.value,
            owner=p.owner_identity,
            created_at=p.created_at.isoformat(),
        )
        for p in platforms[:limit]
    ]
    return PlatformList(items=items, next_cursor=next_cursor)
