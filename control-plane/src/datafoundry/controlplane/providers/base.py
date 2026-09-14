"""Provider adapter framework (T012).

A provider adapter supplies provider constants only (R-02): region list,
region-capability matrix source, Terraform state backend config (R-05), and
credential probe hooks (R-09, FR-018). Adding a provider (e.g. Azure) means
adding a new adapter module + terraform/<provider>/ modules — no changes to
PlatformConfig, API contracts, or existing providers (FR-015).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StateBackendConfig:
    """Terraform state backend configuration for a run (R-05).

    ``type`` is the Terraform backend name (``s3``, ``gcs``, ...); ``config``
    holds backend block attributes. State lives in the *platform's own*
    cloud scope, encrypted, versioned.
    """

    type: str
    config: dict[str, Any]


@dataclass(frozen=True)
class CallerIdentity:
    """Result of a credential probe (R-09: credentials are never persisted)."""

    provider: str
    account_id: str  # AWS account id / GCP project number-or-id
    identity_arn_or_principal: str
    authenticated: bool


class ProviderAdapter(abc.ABC):
    """Abstract base every cloud provider adapter implements."""

    #: Stable provider id used in configs, API paths and DB (``aws``, ``gcp``).
    provider_id: str = ""

    @abc.abstractmethod
    def regions(self) -> tuple[str, ...]:
        """All regions this provider supports."""

    @abc.abstractmethod
    def region_supports(self, region: str, capability_key: str) -> bool:
        """Whether ``region`` supports ``capability_key``.

        Backed by the *generated* region-capability matrix (T061 /
        deployment-api.md §3: generated from actual module availability, not
        hand-maintained).
        """

    @abc.abstractmethod
    def regions_for_capability(self, capability_key: str) -> tuple[str, ...]:
        """Regions supporting ``capability_key`` (used in remediation hints)."""

    @abc.abstractmethod
    def state_backend(
        self, *, platform_name: str, environment: str, run_id: str, region: str
    ) -> StateBackendConfig:
        """Per-run state backend config (R-05, R-06: per-run isolation)."""

    @abc.abstractmethod
    def probe_credentials(self, session: Any | None = None) -> CallerIdentity:
        """Credential probe hook: STS GetCallerIdentity (AWS) / token
        introspection (GCP). Raises ``ProviderAuthError`` when unauthenticated.
        """

    @abc.abstractmethod
    def cloud_scope_id(self, identity: CallerIdentity) -> str:
        """Cloud scope for name-uniqueness (FR-013): account id / project id."""


class ProviderAuthError(RuntimeError):
    """Raised when a credential probe fails (expired/absent credentials)."""


class ProviderNotFoundError(KeyError):
    """Raised when an unknown provider id is requested."""


class ProviderRegistry:
    """Registry of provider adapters (FR-015: registration, not modification)."""

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        if not adapter.provider_id:
            raise ValueError("provider adapter must define provider_id")
        self._adapters[adapter.provider_id] = adapter

    def get(self, provider_id: str) -> ProviderAdapter:
        try:
            return self._adapters[provider_id]
        except KeyError:
            raise ProviderNotFoundError(
                f"unknown provider '{provider_id}'; registered: {sorted(self._adapters)}"
            ) from None

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))


def build_default_registry() -> ProviderRegistry:
    """Registry with the MVP providers (AWS, GCP) registered."""
    from datafoundry.controlplane.providers.aws import AwsAdapter
    from datafoundry.controlplane.providers.gcp import GcpAdapter

    registry = ProviderRegistry()
    registry.register(AwsAdapter())
    registry.register(GcpAdapter())
    return registry


#: Process-wide default provider registry.
default_providers: ProviderRegistry = build_default_registry()
