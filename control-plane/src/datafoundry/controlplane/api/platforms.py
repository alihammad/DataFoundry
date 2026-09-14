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
    ACTION_DESTROY_PLATFORM,
    ACTION_READ_PLATFORM,
    ACTION_UPDATE_PLATFORM,
    Caller,
    require_action,
)
from datafoundry.controlplane.api.deps import (
    get_cloud_gateway,
    get_db,
    get_dispatcher,
    get_settings_from_app,
)
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.capabilities.registry import default_registry
from datafoundry.controlplane.config.settings import Settings
from datafoundry.controlplane.config.validation import (
    config_hash,
    validate_platform_config,
)
from datafoundry.controlplane.db.models import (
    ConfigSource,
    DeploymentRun,
    DeploymentStep,
    Platform,
    PlatformConfigVersion,
    PlatformStatus,
    RunStatus,
    RunType,
)
from datafoundry.controlplane.engine.orchestrator import (
    ActiveRunError,
    Orchestrator,
    has_active_run,
    lock_platform_for_update,
)
from datafoundry.controlplane.providers.base import default_providers
from datafoundry.controlplane.providers.permissions import PermissionChecker
from fastapi import APIRouter, Depends, Header, Query
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


class ConfigExportView(BaseModel):
    version: int
    config_yaml: str
    config_hash: str
    git_ref: str | None = None


class HealthView(BaseModel):
    component: str
    status: str
    last_check_at: str
    detail: str | None = None


class StorageUtilisationView(BaseModel):
    bronze_bytes: int = 0
    silver_bytes: int = 0
    gold_bytes: int = 0


class LatestRunView(BaseModel):
    run_id: uuid.UUID
    status: str
    finished_at: str | None = None
    duration_seconds: float | None = None


class RecentFailureView(BaseModel):
    run_id: uuid.UUID
    step: str
    error: str
    at: str


class PlatformDetail(BaseModel):
    id: uuid.UUID
    name: str
    provider: str
    region: str
    environment_type: str
    status: str
    owner: str
    capabilities_enabled: list[str]
    storage_utilisation: StorageUtilisationView
    health: list[HealthView]
    latest_run: LatestRunView | None = None
    recent_failures: list[RecentFailureView] = []


class DestroyAccepted(BaseModel):
    run_id: uuid.UUID
    run_type: str


class UpdateAccepted(BaseModel):
    platform_id: uuid.UUID
    run_id: uuid.UUID
    status: str


# -- helpers ------------------------------------------------------------------------


def _existing_names(session: Session) -> dict[str, set[str]]:
    """Registered names per ``provider:cloud_scope_id`` (uniqueness rule 8).

    Destroyed platforms do not reserve their name — the name is free to
    reuse after destroy (quickstart Scenario 4 redeploy).
    """
    stmt = select(Platform.provider, Platform.cloud_scope_id, Platform.name).where(
        Platform.status != PlatformStatus.destroyed
    )
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


def _load_platform(session: Session, platform_id: uuid.UUID) -> Platform:
    platform = session.get(Platform, platform_id)
    if platform is None:
        raise NotFoundError(f"platform {platform_id} not found")
    return platform


def _latest_run(session: Session, platform_id: uuid.UUID) -> DeploymentRun | None:
    stmt = (
        select(DeploymentRun)
        .where(DeploymentRun.platform_id == platform_id)
        .order_by(DeploymentRun.created_at.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def _duration_seconds(run: DeploymentRun) -> float | None:
    if run.started_at and run.finished_at:
        return (run.finished_at - run.started_at).total_seconds()
    return None


def _recent_failures(
    session: Session, platform_id: uuid.UUID, limit: int = 5
) -> list[RecentFailureView]:
    from datafoundry.controlplane.db.models import StepStatus

    stmt = (
        select(DeploymentRun, DeploymentStep)
        .join(DeploymentStep, DeploymentStep.run_id == DeploymentRun.id)
        .where(
            DeploymentRun.platform_id == platform_id,
            DeploymentStep.status == StepStatus.failed,
        )
        .order_by(DeploymentRun.created_at.desc(), DeploymentStep.position)
    )
    failures: list[RecentFailureView] = []
    for run, step in session.execute(stmt):
        failures.append(
            RecentFailureView(
                run_id=run.id,
                step=step.key,
                error=step.error_detail or run.failure_summary or "unknown error",
                at=(step.finished_at or run.finished_at or run.created_at).isoformat(),
            )
        )
        if len(failures) >= limit:
            break
    return failures


# -- GET /platforms/{id} (US3 platform detail) -------------------------------------------


@router.get(
    "/platforms/{platform_id}",
    response_model=PlatformDetail,
    dependencies=[Depends(require_action(ACTION_READ_PLATFORM))],
)
def get_platform_detail(
    platform_id: uuid.UUID,
    session: Session = Depends(get_db),
    gateway=Depends(get_cloud_gateway),
) -> PlatformDetail:
    platform = _load_platform(session, platform_id)

    from datafoundry.controlplane.health.service import latest_results
    from datafoundry.controlplane.health.utilisation import collect_utilisation

    latest = latest_results(session, platform.id)
    health = [
        HealthView(
            component=result.component,
            status=result.status.value,
            last_check_at=result.last_check_at.isoformat(),
            detail=result.detail,
        )
        for result in sorted(latest.values(), key=lambda r: r.component)
    ]

    # Enabled capabilities from the current config version.
    capabilities_enabled: list[str] = []
    if platform.current_config_version_id is not None:
        import yaml

        from datafoundry.controlplane.config.schema import PlatformConfig

        stored = session.get(PlatformConfigVersion, platform.current_config_version_id)
        if stored is not None:
            raw = yaml.safe_load(stored.config_yaml)
            config = PlatformConfig.model_validate(raw)
            capabilities_enabled = sorted(
                default_registry.resolve_enabled(config.capabilities.explicitly_enabled())
            )

    utilisation = collect_utilisation(
        gateway,
        platform_name=platform.name,
        environment=platform.environment_type.value,
        provider=platform.provider.value,
    )

    run = _latest_run(session, platform.id)
    latest_run = (
        LatestRunView(
            run_id=run.id,
            status=run.status.value,
            finished_at=run.finished_at.isoformat() if run.finished_at else None,
            duration_seconds=_duration_seconds(run),
        )
        if run is not None
        else None
    )

    return PlatformDetail(
        id=platform.id,
        name=platform.name,
        provider=platform.provider.value,
        region=platform.region,
        environment_type=platform.environment_type.value,
        status=platform.status.value,
        owner=platform.owner_identity,
        capabilities_enabled=capabilities_enabled,
        storage_utilisation=StorageUtilisationView(**utilisation.as_dict()),
        health=health,
        latest_run=latest_run,
        recent_failures=_recent_failures(session, platform.id),
    )


# -- GET /platforms/{id}/config (US2 export) ---------------------------------------------


@router.get(
    "/platforms/{platform_id}/config",
    response_model=ConfigExportView,
    dependencies=[Depends(require_action(ACTION_READ_PLATFORM))],
)
def get_platform_config(
    platform_id: uuid.UUID,
    caller: Caller = Depends(require_action(ACTION_READ_PLATFORM)),
    session: Session = Depends(get_db),
) -> ConfigExportView:
    platform = _load_platform(session, platform_id)
    from datafoundry.controlplane.config.export import ExportSecretLeakError, export_platform

    try:
        exported = export_platform(session, platform)
    except ExportSecretLeakError as exc:
        raise ConflictError("export_refused", str(exc)) from exc

    AuditService(session).config_exported(
        actor=caller.identity,
        platform_id=platform.id,
        version=exported.version,
        config_hash=exported.config_hash,
    )
    session.flush()
    return ConfigExportView(**exported.as_dict())


# -- POST /platforms/{id}/config (US2 update flow) ---------------------------------------


@router.post(
    "/platforms/{platform_id}/config",
    status_code=202,
    response_model=UpdateAccepted,
)
def update_platform_config(
    platform_id: uuid.UUID,
    body: PlatformDeployRequest,
    caller: Caller = Depends(require_action(ACTION_UPDATE_PLATFORM)),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_app),
    dispatch=Depends(get_dispatcher),
) -> UpdateAccepted:
    platform = _load_platform(session, platform_id)
    if platform.status not in (PlatformStatus.ready, PlatformStatus.degraded):
        raise ConflictError(
            "platform_not_updatable",
            f"platform is '{platform.status.value}'; update requires 'ready' or 'degraded'",
        )

    provider_hint = _provider_hint(body.config)
    result = validate_platform_config(
        body.config,
        providers=default_providers,
        registry=default_registry,
        existing_names=_existing_names(session),
        cloud_scope_id=_cloud_scope_id(settings, provider_hint),
    )
    if not result.valid:
        raise ConfigValidationError(result.error_dicts())
    config = result.config
    assert config is not None

    # Production controls on update too (FR-010).
    if config.is_production and not (
        body.approval_ref or (config.approval and config.approval.ref)
    ):
        raise ConfigValidationError(
            [
                {
                    "path": "approval_ref",
                    "code": "approval_required",
                    "message": "production deployments require approval_ref (FR-010)",
                    "remediation": "Pass approval_ref in the request body",
                }
            ]
        )

    # Previous enabled set (for the update plan: re-render only affected modules).
    previous_enabled: set[str] = set()
    if platform.current_config_version_id is not None:
        import yaml

        from datafoundry.controlplane.config.schema import PlatformConfig as PCSchema

        stored = session.get(PlatformConfigVersion, platform.current_config_version_id)
        if stored is not None:
            prev_config = PCSchema.model_validate(yaml.safe_load(stored.config_yaml))
            previous_enabled = default_registry.resolve_enabled(
                prev_config.capabilities.explicitly_enabled()
            )

    from datafoundry.controlplane.config.versioning import version_config

    outcome = version_config(
        session,
        platform=platform,
        raw_config=body.config,
        created_by=caller.identity,
        source=ConfigSource.api,
    )

    lock_platform_for_update(session, platform.id)
    if has_active_run(session, platform.id):
        raise ConflictError("active_run", "platform already has an active run")

    orchestrator = Orchestrator(session, registry=default_registry)
    platform.status = PlatformStatus.deploying
    session.flush()
    run = orchestrator.queue_update(
        platform=platform,
        config=config,
        config_version=outcome.version,
        previous_enabled=previous_enabled,
        initiated_by=caller.identity,
        approval_ref=body.approval_ref or (config.approval.ref if config.approval else None),
    )

    AuditService(session).record(
        actor=caller.identity,
        action="config.updated",
        platform_id=platform.id,
        payload={
            "run_id": str(run.id),
            "config_version": outcome.version.version,
            "config_hash": config_hash(body.config),
        },
    )
    session.flush()
    dispatch(run.id)
    return UpdateAccepted(platform_id=platform.id, run_id=run.id, status=run.status.value)


# -- DELETE /platforms/{id} (US2 destroy flow) -------------------------------------------


@router.delete(
    "/platforms/{platform_id}",
    status_code=202,
    response_model=DestroyAccepted,
)
def destroy_platform(
    platform_id: uuid.UUID,
    caller: Caller = Depends(require_action(ACTION_DESTROY_PLATFORM)),
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_app),
    gateway=Depends(get_cloud_gateway),
    approval_ref: str | None = Query(default=None),
) -> DestroyAccepted:
    platform = _load_platform(session, platform_id)

    # Production destroy requires approval_ref (deployment-api.md §1).
    if platform.environment_type.value == "production" and not approval_ref:
        raise ConfigValidationError(
            [
                {
                    "path": "approval_ref",
                    "code": "approval_required",
                    "message": "destroying a production platform requires approval_ref (FR-010)",
                    "remediation": "Pass ?approval_ref=<ticket> as a query parameter",
                }
            ]
        )

    if platform.status is PlatformStatus.destroyed:
        raise ConflictError("already_destroyed", "platform is already destroyed")

    lock_platform_for_update(session, platform.id)
    if has_active_run(session, platform.id):
        raise ConflictError("active_run", "platform has an active run; wait for it to finish")

    # Create a destroy run with the current config version (or synthetic).
    config_version_id = platform.current_config_version_id
    run = DeploymentRun(
        platform_id=platform.id,
        config_version_id=config_version_id,
        run_type=RunType.destroy,
        status=RunStatus.queued,
        initiated_by=caller.identity,
        approval_ref=approval_ref,
        terraform_workspace=f"run-{uuid.uuid4().hex[:12]}",
    )
    session.add(run)
    session.flush()

    AuditService(session).destroy_requested(
        actor=caller.identity, platform_id=platform.id, run_id=run.id, approval_ref=approval_ref
    )
    session.flush()

    # Execute the destroy synchronously via the recovery runner (reverse-order
    # teardown). In production this would dispatch to a worker; the runner is
    # synchronous here so the run reaches rolled_back/destroyed immediately.
    from datafoundry.controlplane.engine.recovery import RecoveryRunner

    recovery = RecoveryRunner(session, settings=settings, gateway=gateway)
    run.status = RunStatus.running
    session.flush()
    try:
        recovery.destroy(run.id)
    except Exception:
        session.rollback()
        raise
    # Free the name for redeploy (SC-002 reproducibility): rename the
    # destroyed platform so the (provider, cloud_scope_id, name) unique
    # constraint no longer reserves it (quickstart Scenario 4 redeploys the
    # same name).
    platform.name = f"{platform.name}-destroyed-{platform.id.hex[:8]}"
    session.flush()
    return DestroyAccepted(run_id=run.id, run_type="destroy")
