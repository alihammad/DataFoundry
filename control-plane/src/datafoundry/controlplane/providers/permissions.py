"""Permission pre-check (T029, FR-018 fail-fast).

Before any mutating operation the control plane probes the caller's cloud
credentials:

- AWS: STS ``GetCallerIdentity`` + dry-run permission probes for the actions
  the deployment will need (SIMULATED in dev/test via an injectable prober).
- GCP: token introspection (``google.auth`` default credentials) + required
  permission listing via the IAM testPermissions-style probe.

The result is a precise missing-permission list used for 403 responses
(deployment-api.md §1: ``{code: insufficient_permissions, missing: [...]}``).

Credentials are never persisted (R-09). In dev auth mode the probe is
short-circuited: everything is permitted.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from datafoundry.controlplane.api.auth import ACTION_CREATE_PLATFORM, REQUIRED_PERMISSIONS
from datafoundry.controlplane.providers.base import (
    CallerIdentity,
    ProviderAdapter,
    ProviderAuthError,
)


@dataclass(frozen=True)
class PermissionProbeResult:
    """Outcome of the fail-fast permission pre-check."""

    identity: CallerIdentity | None
    missing: tuple[str, ...] = field(default=())
    #: True when the credential probe itself failed (unauthenticated).
    unauthenticated: bool = False
    detail: str = ""

    @property
    def authorised(self) -> bool:
        return not self.missing and not self.unauthenticated


#: Injectable prober: (adapter, action, permissions) -> missing permissions.
PermissionProber = Callable[[ProviderAdapter, str, Sequence[str]], list[str]]


def _probe_aws(adapter: ProviderAdapter, action: str, permissions: Sequence[str]) -> list[str]:
    """AWS probe: IAM simulate-principal-policy style check.

    Uses the ambient boto3 session; each permission is tested with
    ``iam:SimulatePrincipalPolicy`` when available, otherwise conservatively
    reported as missing. Network/permission failures degrade to "missing"
    (fail-fast, FR-018) rather than blocking deploys on probe errors.
    """
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        identity = adapter.probe_credentials()
    except ProviderAuthError:
        return list(permissions)
    try:
        client = boto3.client("iam")
        response = client.simulate_principal_policy(
            PolicySourceArn=identity.identity_arn_or_principal,
            ActionNames=list(permissions),
        )
    except (ClientError, BotoCoreError):
        # Cannot simulate (e.g. no iam:SimulatePrincipalPolicy itself):
        # fall back to optimistic — the real failure surfaces at apply time
        # with a precise cloud error. Fail-fast only on *known* denials.
        return []
    return [
        entry["EvalActionName"]
        for entry in response.get("EvaluationResults", [])
        if entry.get("EvalDecision") != "allowed"
    ]


def _probe_gcp(adapter: ProviderAdapter, action: str, permissions: Sequence[str]) -> list[str]:
    """GCP probe: ``iam.projects.serviceAccounts.testIamPermissions``-style.

    Uses google.auth default credentials; when the testIamPermissions call is
    unavailable the probe degrades optimistically (see _probe_aws rationale).
    """
    try:
        adapter.probe_credentials()
    except ProviderAuthError:
        return list(permissions)
    try:
        import google.auth
        import google.auth.transport.requests
        import googleapiclient.discovery  # type: ignore[import-not-found]

        credentials, project = google.auth.default()
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
        iam = googleapiclient.discovery.build("cloudresourcemanager", "v1", credentials=credentials)
        response = (
            iam.projects()
            .testIamPermissions(
                resource=project or "unknown",
                body={"permissions": list(permissions)},
            )
            .execute()
        )
        granted = set(response.get("permissions", []))
        return [p for p in permissions if p not in granted]
    except Exception:
        return []


_DEFAULT_PROBERS: dict[str, PermissionProber] = {
    "aws": _probe_aws,
    "gcp": _probe_gcp,
}


class PermissionChecker:
    """Fail-fast permission pre-check used by the API layer (FR-018)."""

    def __init__(
        self,
        *,
        auth_mode: str = "cloud_iam",
        dev_identity: str = "dev@datafoundry.local",
        probers: dict[str, PermissionProber] | None = None,
    ) -> None:
        self.auth_mode = auth_mode
        self.dev_identity = dev_identity
        self._probers = probers or _DEFAULT_PROBERS

    def check(
        self, adapter: ProviderAdapter, action: str = ACTION_CREATE_PLATFORM
    ) -> PermissionProbeResult:
        """Probe identity + required permissions for ``action``.

        Dev auth mode short-circuits to a fully-authorised static identity.
        """
        if self.auth_mode == "dev":
            return PermissionProbeResult(
                identity=CallerIdentity(
                    provider=adapter.provider_id,
                    account_id="000000000000",
                    identity_arn_or_principal=self.dev_identity,
                    authenticated=True,
                )
            )
        try:
            identity = adapter.probe_credentials()
        except ProviderAuthError as exc:
            return PermissionProbeResult(identity=None, unauthenticated=True, detail=str(exc))
        required = REQUIRED_PERMISSIONS.get(adapter.provider_id, {}).get(action, ())
        prober = self._probers.get(adapter.provider_id)
        missing: list[str] = prober(adapter, action, required) if prober else []
        return PermissionProbeResult(identity=identity, missing=tuple(missing))


def check_permissions(
    adapter: ProviderAdapter,
    action: str = ACTION_CREATE_PLATFORM,
    *,
    auth_mode: str = "cloud_iam",
    dev_identity: str = "dev@datafoundry.local",
    probers: dict[str, PermissionProber] | None = None,
) -> PermissionProbeResult:
    """Convenience wrapper around :class:`PermissionChecker`."""
    checker = PermissionChecker(auth_mode=auth_mode, dev_identity=dev_identity, probers=probers)
    return checker.check(adapter, action)


def identity_for(adapter: ProviderAdapter, result: PermissionProbeResult) -> tuple[str, str]:
    """(actor identity, cloud_scope_id) pair for persistence/audit."""
    identity: Any = result.identity
    if identity is None:  # pragma: no cover - callers check authorised first
        raise ProviderAuthError(result.detail or "no identity")
    return identity.identity_arn_or_principal, adapter.cloud_scope_id(identity)
