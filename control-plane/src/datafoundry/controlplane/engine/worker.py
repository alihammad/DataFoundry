"""Async deployment worker (T032, R-01, R-11).

Supervises the per-step execution of a DeploymentRun:

- Streams progress into DeploymentStep rows, checkpointing every state change
  to PostgreSQL (R-01: the DB is the source of truth, not worker memory).
- Simulated mode (dev/tests, ``settings.simulate_cloud``): steps execute
  against the in-memory CloudGateway — no terraform binary needed.
- Real mode: renders the per-run root module (T016), runs ``terraform
  init/validate/plan`` for the pre-flight steps and per-module
  ``terraform apply -target=module.<key>`` for capability steps, parsing
  ``-json`` output into step updates.
- Fault injection (dev only): ``DF_FAULT_INJECTION=1`` fails the step named
  by ``DF_FAULT_INJECTION_STEP`` (quickstart Scenario 3).
- Credential expiry => run ``paused`` (never auto-destroy, R-06).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.api.auth import ACTION_CREATE_PLATFORM
from datafoundry.controlplane.capabilities.registry import default_registry
from datafoundry.controlplane.config.schema import PlatformConfig
from datafoundry.controlplane.config.secret_scan import redact_text
from datafoundry.controlplane.config.settings import Settings
from datafoundry.controlplane.config.validation import (
    translate_terraform_errors,
    validate_platform_config,
)
from datafoundry.controlplane.db.models import (
    DeploymentRun,
    DeploymentStep,
    HealthCheckResult,
    HealthStatus,
    Platform,
    PlatformStatus,
    RunStatus,
    StepStatus,
)
from datafoundry.controlplane.db.state_machines import (
    can_transition_platform,
    transition_platform,
    transition_run,
)
from datafoundry.controlplane.engine.gateway import CloudGateway, ResourceRecord
from datafoundry.controlplane.engine.init_jobs import (
    initialise_catalog,
    initialise_storage_zones,
    platform_bucket,
)
from datafoundry.controlplane.engine.orchestrator import (
    APPROVAL_GATE_STEP,
    HEALTH_CHECKS_STEP,
)
from datafoundry.controlplane.health.framework import (
    HealthCheckTarget,
    RunnerRegistry,
    evaluate_platform_status,
)
from datafoundry.controlplane.health.runners import default_runners
from datafoundry.controlplane.providers.base import ProviderAuthError, default_providers
from datafoundry.controlplane.providers.permissions import PermissionChecker
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class StepExecutionError(RuntimeError):
    """A deployment step failed. ``detail`` is user-facing (redacted)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass
class StepContext:
    """Everything a step execution needs (built once per run)."""

    run: DeploymentRun
    platform: Platform
    config: PlatformConfig
    raw_config: dict[str, Any]
    gateway: CloudGateway
    settings: Settings
    bucket: str
    catalog_endpoint: str


class WorkerRunner:
    """Executes deployment runs step-by-step with DB checkpointing."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings,
        gateway: CloudGateway,
        runners: RunnerRegistry | None = None,
        permission_checker: PermissionChecker | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.gateway = gateway
        self.runners = runners or default_runners
        self.permission_checker = permission_checker or PermissionChecker(
            auth_mode=settings.auth_mode, dev_identity=settings.dev_identity
        )

    # -- public API -----------------------------------------------------------

    def process_run(self, run_id: uuid.UUID) -> DeploymentRun:
        """Execute (or resume) a run to its next terminal/paused state."""
        run = self.session.get(DeploymentRun, run_id)
        if run is None:
            raise KeyError(f"run {run_id} not found")
        ctx = self._build_context(run)
        self._start_run(run, ctx.platform)
        try:
            self._execute_steps(ctx)
        except PausedSignalError:
            run.status = transition_run(run.status, RunStatus.paused)
            run.failure_summary = "credentials expired — run paused, resume after refresh"
            self.session.flush()
            return run
        except StepExecutionError as exc:
            self._fail_run(run, ctx.platform, exc.detail)
            return run
        self._finish_run(run, ctx)
        return run

    # -- context ----------------------------------------------------------------

    def _build_context(self, run: DeploymentRun) -> StepContext:
        import yaml

        platform = self.session.get(Platform, run.platform_id)
        assert platform is not None
        raw_config = yaml.safe_load(run.config_version.config_yaml)
        config = PlatformConfig.model_validate(raw_config)
        bucket = platform_bucket(
            platform.name, platform.environment_type.value, platform.provider.value
        )
        catalog_endpoint = f"https://catalog.{platform.name}.datafoundry.internal"
        return StepContext(
            run=run,
            platform=platform,
            config=config,
            raw_config=raw_config,
            gateway=self.gateway,
            settings=self.settings,
            bucket=bucket,
            catalog_endpoint=catalog_endpoint,
        )

    # -- run lifecycle ------------------------------------------------------------

    def _start_run(self, run: DeploymentRun, platform: Platform) -> None:
        run.status = transition_run(run.status, RunStatus.running)
        if run.started_at is None:
            run.started_at = datetime.now(UTC)
        platform.status = transition_platform(platform.status, PlatformStatus.deploying)
        self.session.flush()

    def _fail_run(self, run: DeploymentRun, platform: Platform, detail: str) -> None:
        run.status = transition_run(run.status, RunStatus.failed)
        run.finished_at = datetime.now(UTC)
        run.failure_summary = redact_text(detail)
        # Health-check failures leave the platform `degraded` (US3-AC2); only
        # move to `failed` when the state machine allows it.
        if can_transition_platform(platform.status, PlatformStatus.failed):
            platform.status = PlatformStatus.failed
        self.session.flush()

    def _finish_run(self, run: DeploymentRun, ctx: StepContext) -> None:
        run.status = transition_run(run.status, RunStatus.succeeded)
        run.finished_at = datetime.now(UTC)
        self.session.flush()

    # -- step execution -------------------------------------------------------------

    def _ordered_steps(self, run: DeploymentRun) -> list[DeploymentStep]:
        stmt = (
            select(DeploymentStep)
            .where(DeploymentStep.run_id == run.id)
            .order_by(DeploymentStep.position)
        )
        return list(self.session.execute(stmt).scalars())

    def _execute_steps(self, ctx: StepContext) -> None:
        for step in self._ordered_steps(ctx.run):
            if step.status in (StepStatus.succeeded, StepStatus.skipped):
                continue  # retry: never re-execute succeeded steps (FR-009)
            if step.status is StepStatus.pending or step.status is StepStatus.failed:
                self._execute_step(ctx, step)

    def _execute_step(self, ctx: StepContext, step: DeploymentStep) -> None:
        step.status = StepStatus.running
        step.attempt += 1
        step.started_at = datetime.now(UTC)
        step.error_detail = None
        self.session.flush()  # checkpoint: visible via GET /runs/{id}
        logger.info("step.start", extra={"run_id": str(ctx.run.id), "step": step.key})
        try:
            self._maybe_inject_fault(step)
            self._dispatch_step(ctx, step)
        except ProviderAuthError as exc:
            step.status = StepStatus.failed
            step.finished_at = datetime.now(UTC)
            step.error_detail = redact_text(f"credentials expired: {exc}")
            self.session.flush()
            raise PausedSignalError from exc
        except StepExecutionError as exc:
            step.status = StepStatus.failed
            step.finished_at = datetime.now(UTC)
            step.error_detail = redact_text(exc.detail)
            self.session.flush()
            raise
        except Exception as exc:
            step.status = StepStatus.failed
            step.finished_at = datetime.now(UTC)
            step.error_detail = redact_text(f"{type(exc).__name__}: {exc}")
            self.session.flush()
            raise StepExecutionError(step.error_detail or "step failed") from exc
        step.status = StepStatus.succeeded
        step.finished_at = datetime.now(UTC)
        self.session.flush()
        logger.info("step.done", extra={"run_id": str(ctx.run.id), "step": step.key})

    def _maybe_inject_fault(self, step: DeploymentStep) -> None:
        """Dev-only fault injection (quickstart Scenario 3)."""
        if not self.settings.fault_injection:
            return
        target = self.settings.fault_injection_step
        if step.key == target or step.capability == target:
            raise StepExecutionError(
                f"Quota exceeded: {step.key} could not be provisioned "
                "(simulated fault injection, DF_FAULT_INJECTION)"
            )

    def _dispatch_step(self, ctx: StepContext, step: DeploymentStep) -> None:
        handlers = {
            "validate-config": self._step_validate_config,
            "generate-tf": self._step_generate_tf,
            "validate-tf": self._step_validate_tf,
            "permission-check": self._step_permission_check,
            APPROVAL_GATE_STEP: self._step_approval_gate,
            HEALTH_CHECKS_STEP: self._step_health_checks,
        }
        handler = handlers.get(step.key)
        if handler is not None:
            handler(ctx, step)
            return
        if step.capability is not None:
            self._step_capability(ctx, step)
            return
        raise StepExecutionError(f"unknown step '{step.key}'")

    # -- individual steps -----------------------------------------------------------

    def _step_validate_config(self, ctx: StepContext, step: DeploymentStep) -> None:
        result = validate_platform_config(
            ctx.raw_config, providers=default_providers, registry=default_registry
        )
        if not result.valid:
            summary = "; ".join(e.message for e in result.errors[:5])
            raise StepExecutionError(f"config validation failed: {summary}")

    def _step_generate_tf(self, ctx: StepContext, step: DeploymentStep) -> None:
        from datafoundry.controlplane.engine.generator import RootModuleGenerator

        adapter = default_providers.get(ctx.config.platform.provider)
        generator = RootModuleGenerator(default_registry)
        workdir = self.settings.workspaces_dir / str(ctx.run.id)
        generator.write(
            ctx.config,
            adapter,
            run_id=str(ctx.run.id),
            workdir=workdir,
            backend=adapter.state_backend(
                platform_name=ctx.platform.name,
                environment=ctx.platform.environment_type.value,
                run_id=str(ctx.run.id),
                region=ctx.platform.region,
            ),
        )
        step.detail = f"rendered {workdir / 'main.tf.json'}"

    def _step_validate_tf(self, ctx: StepContext, step: DeploymentStep) -> None:
        if self.settings.simulate_cloud:
            step.detail = "simulated: terraform validate/plan skipped"
            return
        from datafoundry.controlplane.engine.terraform import TerraformCLI, TerraformError

        cli = TerraformCLI(self.settings)
        workdir = self.settings.workspaces_dir / str(ctx.run.id)

        async def _run() -> None:
            await cli.init(workdir)
            events = await cli.validate(workdir)
            await cli.plan(workdir)
            errors = translate_terraform_errors(events)
            if errors:
                raise StepExecutionError(
                    "terraform validate failed: " + "; ".join(e.message for e in errors)
                )

        try:
            asyncio.run(_run())
        except TerraformError as exc:
            errors = translate_terraform_errors(exc.events)
            detail = "; ".join(e.message for e in errors) or str(exc)
            raise StepExecutionError(f"terraform validate/plan failed: {detail}") from exc

    def _step_permission_check(self, ctx: StepContext, step: DeploymentStep) -> None:
        adapter = default_providers.get(ctx.config.platform.provider)
        result = self.permission_checker.check(adapter, ACTION_CREATE_PLATFORM)
        if result.unauthenticated:
            raise ProviderAuthError(result.detail or "credential probe failed")
        if not result.authorised:
            raise StepExecutionError(
                "insufficient permissions: missing " + ", ".join(result.missing)
            )

    def _step_approval_gate(self, ctx: StepContext, step: DeploymentStep) -> None:
        approval_ref = ctx.run.approval_ref or (
            ctx.config.approval.ref if ctx.config.approval else None
        )
        if not approval_ref:
            raise StepExecutionError("production deployment requires an approval_ref (FR-010)")
        step.detail = f"approval {approval_ref} verified"

    def _step_capability(self, ctx: StepContext, step: DeploymentStep) -> None:
        capability = step.capability
        assert capability is not None
        if self.settings.simulate_cloud:
            self._simulate_capability(ctx, step, capability)
        else:
            self._terraform_capability(ctx, step, capability)

    def _simulate_capability(self, ctx: StepContext, step: DeploymentStep, capability: str) -> None:
        run_id = str(ctx.run.id)
        gateway = ctx.gateway
        # Record the module's resources in the run inventory (rollback scope).
        if hasattr(gateway, "_add"):  # SimulatedCloudGateway
            gateway._add(
                ResourceRecord(
                    run_id=run_id,
                    kind="module",
                    identifier=f"{capability}@{step.terraform_module or capability}",
                    capability=capability,
                )
            )
        if capability == "storage_zones":
            initialise_storage_zones(
                gateway,
                run_id=run_id,
                platform_name=ctx.platform.name,
                environment=ctx.platform.environment_type.value,
                provider=ctx.platform.provider.value,
            )
        if capability == "catalog":
            enabled = sorted(
                default_registry.resolve_enabled(ctx.config.capabilities.explicitly_enabled())
            )
            initialise_catalog(
                gateway,
                run_id=run_id,
                platform_name=ctx.platform.name,
                environment=ctx.platform.environment_type.value,
                provider=ctx.platform.provider.value,
                catalog_endpoint=ctx.catalog_endpoint,
                capabilities_enabled=enabled,
            )

    def _terraform_capability(
        self, ctx: StepContext, step: DeploymentStep, capability: str
    ) -> None:
        from datafoundry.controlplane.engine.terraform import TerraformCLI, TerraformError

        cli = TerraformCLI(self.settings)
        workdir = self.settings.workspaces_dir / str(ctx.run.id)
        target = f"module.{capability}"

        # Per-module apply keeps step granularity (FR-008/FR-009). Terraform
        # -target limits the apply to this capability's module subgraph.
        async def _apply_targeted() -> None:
            await cli.init(workdir)
            await cli.select_workspace(workdir, ctx.run.terraform_workspace)
            await cli.run_json(["apply", "-auto-approve", f"-target={target}"], workdir=workdir)

        try:
            asyncio.run(_apply_targeted())
        except TerraformError as exc:
            errors = translate_terraform_errors(exc.events)
            detail = "; ".join(e.message for e in errors) or exc.stderr or str(exc)
            raise StepExecutionError(f"{capability} apply failed: {detail}") from exc

        if capability == "storage_zones":
            initialise_storage_zones(
                ctx.gateway,
                run_id=str(ctx.run.id),
                platform_name=ctx.platform.name,
                environment=ctx.platform.environment_type.value,
                provider=ctx.platform.provider.value,
            )
        if capability == "catalog":
            initialise_catalog(
                ctx.gateway,
                run_id=str(ctx.run.id),
                platform_name=ctx.platform.name,
                environment=ctx.platform.environment_type.value,
                provider=ctx.platform.provider.value,
                catalog_endpoint=ctx.catalog_endpoint,
                capabilities_enabled=sorted(
                    default_registry.resolve_enabled(ctx.config.capabilities.explicitly_enabled())
                ),
            )

    # -- health checks (step 15, R-08/FR-007) ----------------------------------------

    def _step_health_checks(self, ctx: StepContext, step: DeploymentStep) -> None:
        enabled = default_registry.resolve_enabled(ctx.config.capabilities.explicitly_enabled())
        targets = self._resolve_targets(ctx, enabled)
        latest: dict[str, HealthStatus] = {}
        unhealthy: list[str] = []
        for capability in sorted(enabled):
            target = targets[capability]
            runner = self.runners.get(target.runner_id)
            outcome = runner.run(target, ctx.gateway)
            latest[capability] = outcome.status
            self.session.add(
                HealthCheckResult(
                    platform_id=ctx.platform.id,
                    component=capability,
                    status=outcome.status,
                    last_check_at=outcome.checked_at(),
                    detail=outcome.detail,
                    run_id=ctx.run.id,
                )
            )
            if outcome.status is not HealthStatus.healthy:
                unhealthy.append(f"{capability}: {outcome.detail or outcome.status.value}")
        self.session.flush()

        overall = evaluate_platform_status(latest, enabled)
        if overall is HealthStatus.healthy:
            ctx.platform.status = transition_platform(ctx.platform.status, PlatformStatus.ready)
            step.detail = f"all {len(enabled)} enabled capabilities healthy"
        else:
            ctx.platform.status = transition_platform(ctx.platform.status, PlatformStatus.degraded)
            step.detail = "unhealthy components: " + "; ".join(unhealthy)
            raise StepExecutionError(
                "health checks failed — platform degraded: " + "; ".join(unhealthy)
            )

    def _resolve_targets(self, ctx: StepContext, enabled: set[str]) -> dict[str, HealthCheckTarget]:
        """Map enabled capabilities to health targets from run outputs.

        Simulated mode synthesises deterministic targets; real mode would read
        ``terraform output`` (health_target per capability module).
        """
        targets: dict[str, HealthCheckTarget] = {}
        name = ctx.platform.name
        for capability in enabled:
            runner_id = default_registry.get(capability).health_check
            target = ""
            context: dict[str, Any] | None = None
            if capability == "networking":
                target = f"vpc.{name}.datafoundry.internal"
            elif capability == "secrets":
                target = (
                    ctx.config.encryption.at_rest.kms_key_ref
                    if ctx.config.encryption
                    else "platform-cmk"
                )
            elif capability == "storage_zones":
                target = ctx.bucket
                context = {"bucket": ctx.bucket}
            elif capability == "iam":
                target = f"datafoundry-{name}-role"
            elif capability == "compute":
                target = f"compute.{name}.datafoundry.internal"
            elif capability == "database":
                target = f"db.{name}.datafoundry.internal:5432"
            elif capability == "catalog":
                target = ctx.catalog_endpoint
            elif capability == "orchestration":
                target = f"https://airflow.{name}.datafoundry.internal"
            elif capability == "ingestion":
                target = f"https://ingestion.{name}.datafoundry.internal"
            elif capability == "quality":
                target = f"quality-runner.{name}.datafoundry.internal"
            elif capability == "semantic_layer":
                target = f"https://semantic.{name}.datafoundry.internal"
            elif capability == "monitoring":
                target = f"otel-collector.{name}.datafoundry.internal"
            targets[capability] = HealthCheckTarget(
                capability=capability,
                runner_id=runner_id,
                target=target,
                context=context,
            )
        return targets


class PausedSignalError(Exception):
    """Internal: credential expiry => run paused (R-06)."""
