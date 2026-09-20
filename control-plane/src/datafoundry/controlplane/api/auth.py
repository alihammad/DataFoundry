"""AuthN/AuthZ dependency (T018).

Federated cloud IAM identity extraction with caller-identity propagation and
authorisation check hooks for platform create/update/destroy. Missing
permissions produce 403 with the precise missing-permission list (FR-018,
deployment-api.md cross-cutting rules).

Modes (settings.auth_mode):
- ``dev``: static local identity (development only).
- ``cloud_iam``: bearer token verified via the provider adapters' credential
  probe hooks (STS / token introspection, R-09 — credentials never persisted).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from datafoundry.controlplane.api.errors import ForbiddenError
from datafoundry.controlplane.config.settings import Settings, get_settings
from fastapi import Depends, Request

#: Actions guarded by authorisation checks.
ACTION_CREATE_PLATFORM = "platform.create"
ACTION_UPDATE_PLATFORM = "platform.update"
ACTION_DESTROY_PLATFORM = "platform.destroy"
ACTION_READ_PLATFORM = "platform.read"

#: Permission names surfaced in 403 responses (per provider, FR-018).
REQUIRED_PERMISSIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "aws": {
        ACTION_CREATE_PLATFORM: (
            "iam:CreateRole",
            "s3:CreateBucket",
            "kms:CreateKey",
            "cloudformation:CreateStack",
        ),
        ACTION_UPDATE_PLATFORM: ("iam:CreateRole", "s3:CreateBucket"),
        ACTION_DESTROY_PLATFORM: (
            "iam:DeleteRole",
            "s3:DeleteBucket",
            "kms:ScheduleKeyDeletion",
        ),
        ACTION_READ_PLATFORM: (),
    },
    "gcp": {
        ACTION_CREATE_PLATFORM: (
            "compute.networks.create",
            "storage.buckets.create",
            "cloudkms.cryptoKeys.create",
            "iam.serviceAccounts.create",
        ),
        ACTION_UPDATE_PLATFORM: ("storage.buckets.create", "iam.serviceAccounts.create"),
        ACTION_DESTROY_PLATFORM: (
            "storage.buckets.delete",
            "cloudkms.cryptoKeys.setIamPolicy",
            "iam.serviceAccounts.delete",
        ),
        ACTION_READ_PLATFORM: (),
    },
}


@dataclass(frozen=True)
class Caller:
    """Authenticated caller identity (propagated to audit records, FR-014)."""

    identity: str
    provider: str | None = None
    account_id: str | None = None
    #: RBAC roles for the caller (feature 005 FR-012/FR-013). Populated from
    #: the dev identity's roles in dev mode; from federated IAM in cloud mode.
    roles: tuple[str, ...] = field(default=())
    #: Permissions the caller was *denied* during pre-checks (empty = fully
    #: authorised). Populated by the permission pre-check (T029).
    missing_permissions: tuple[str, ...] = field(default=())


class Authorizer:
    """Authorisation check hooks.

    MVP: static permission model — the caller is authorised for an action
    unless the provider permission pre-check (T029) reports missing
    permissions. Hooks are methods so later phases (feature 005 governance)
    can override policy without touching call sites.
    """

    def check(self, caller: Caller, action: str, *, provider: str | None = None) -> None:
        """Raise ForbiddenError when the caller lacks permissions for action."""
        if caller.missing_permissions:
            raise ForbiddenError(list(caller.missing_permissions))
        # Unknown provider/action combos default to allowed at MVP;
        # T029 performs the live probe before any mutating operation and
        # returns a Caller with missing_permissions populated.
        _ = self.required_permissions(action, provider or "")

    def required_permissions(self, action: str, provider: str) -> tuple[str, ...]:
        return REQUIRED_PERMISSIONS.get(provider, {}).get(action, ())


_default_authorizer = Authorizer()


def get_authorizer() -> Authorizer:
    return _default_authorizer


async def _extract_cloud_iam_identity(request: Request) -> Caller:
    """Bearer-token identity extraction via provider credential probes."""
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise ForbiddenError(
            ["authenticated identity"],
            detail="Missing bearer token (federated cloud IAM identity required)",
        )
    provider = request.headers.get("x-datafoundry-provider", "").lower()
    if provider not in ("aws", "gcp"):
        raise ForbiddenError(
            ["provider identification"],
            detail="x-datafoundry-provider header must be 'aws' or 'gcp'",
        )
    from datafoundry.controlplane.providers.base import ProviderAuthError, default_providers

    adapter = default_providers.get(provider)
    try:
        identity = adapter.probe_credentials(session=_session_from_request(request))
    except ProviderAuthError as exc:
        raise ForbiddenError(
            ["valid cloud credentials"], detail=f"Credential probe failed: {exc}"
        ) from exc
    return Caller(
        identity=identity.identity_arn_or_principal,
        provider=provider,
        account_id=adapter.cloud_scope_id(identity),
    )


def _session_from_request(request: Request) -> Any | None:
    """Optional pre-built provider session attached by middleware/tests."""
    return getattr(request.state, "provider_session", None)


async def get_caller(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Caller:
    """FastAPI dependency: authenticated caller identity."""
    if settings.auth_mode == "dev":
        return Caller(
            identity=settings.dev_identity,
            roles=tuple(settings.dev_roles),
        )
    return await _extract_cloud_iam_identity(request)


def require_action(action: str):
    """Dependency factory: authorise the caller for ``action``.

    Usage::

        @router.post("/platforms", dependencies=[Depends(require_action(ACTION_CREATE_PLATFORM))])
    """

    async def _dependency(
        request: Request,
        caller: Caller = Depends(get_caller),
        authorizer: Authorizer = Depends(get_authorizer),
    ) -> Caller:
        provider = request.headers.get("x-datafoundry-provider", "").lower() or None
        authorizer.check(caller, action, provider=provider)
        return caller

    return _dependency
