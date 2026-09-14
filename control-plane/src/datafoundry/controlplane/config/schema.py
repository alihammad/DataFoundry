"""PlatformConfig Pydantic v2 model (T009).

Source of truth for contracts/platform-config-schema.md. Strict: unknown
fields are rejected at every level and no implicit type coercion is applied.

This module covers *structural* validation (rules 1-3 of the validation
contract: YAML structure, types/enums/formats, naming). Cross-cutting
semantic rules (region-capability matrix, dependency closure, production
controls, secret scan, uniqueness) are collected by
``controlplane.config.validation`` (T028) so that ALL errors are returned in
one 422 response (FR-003, SC-004).
"""

from __future__ import annotations

import ipaddress
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

API_VERSION = "datafoundry/v1"
KIND = "PlatformConfig"

PLATFORM_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
RESERVED_NAMES = frozenset({"datafoundry", "system"})

Provider = Literal["aws", "gcp"]
Environment = Literal["development", "test", "uat", "production"]
Isolation = Literal["private", "internal", "public"]
ComputeSize = Literal["small", "medium", "large"]

#: Capabilities that are always provisioned (mandatory core, capability-catalog.md).
CORE_CAPABILITIES = ("networking", "secrets", "storage_zones", "iam")

#: Selectable capabilities that may appear in the config ``capabilities`` block.
SELECTABLE_CAPABILITIES = (
    "compute",
    "database",
    "catalog",
    "orchestration",
    "ingestion",
    "quality",
    "semantic_layer",
    "monitoring",
)

_STRICT = ConfigDict(strict=True, extra="forbid")


class _StrictModel(BaseModel):
    model_config = _STRICT


class PlatformSection(_StrictModel):
    name: str
    provider: Provider
    region: str
    environment: Environment

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        if not PLATFORM_NAME_RE.match(v):
            raise ValueError(
                "platform.name must match ^[a-z][a-z0-9-]{2,62}$ "
                "(lowercase letter first, then lowercase letters/digits/hyphens, 3-63 chars)"
            )
        if v in RESERVED_NAMES:
            raise ValueError(f"platform.name '{v}' is reserved")
        return v

    @field_validator("region")
    @classmethod
    def _validate_region_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("platform.region must not be empty")
        return v


class CapabilitySettings(_StrictModel):
    """One ``capabilities.<key>`` entry: ``{enabled: bool, ...}``."""

    enabled: bool


class ComputeSettings(CapabilitySettings):
    size: ComputeSize = "small"


class CapabilitiesSection(_StrictModel):
    # Mandatory core - must be present and enabled.
    networking: CapabilitySettings
    secrets: CapabilitySettings
    storage_zones: CapabilitySettings
    iam: CapabilitySettings
    # Selectable - default disabled when omitted.
    compute: ComputeSettings = Field(default_factory=lambda: ComputeSettings(enabled=False))
    catalog: CapabilitySettings = Field(default_factory=lambda: CapabilitySettings(enabled=False))
    orchestration: CapabilitySettings = Field(
        default_factory=lambda: CapabilitySettings(enabled=False)
    )
    ingestion: CapabilitySettings = Field(default_factory=lambda: CapabilitySettings(enabled=False))
    quality: CapabilitySettings = Field(default_factory=lambda: CapabilitySettings(enabled=False))
    semantic_layer: CapabilitySettings = Field(
        default_factory=lambda: CapabilitySettings(enabled=False)
    )
    monitoring: CapabilitySettings = Field(
        default_factory=lambda: CapabilitySettings(enabled=False)
    )
    # ``database`` is auto-enabled when catalog/orchestration/ingestion/quality/
    # semantic_layer is enabled (capability-catalog.md footnote). It may also be
    # requested explicitly; ``None`` means "resolve implicitly".
    database: CapabilitySettings | None = None

    @model_validator(mode="after")
    def _core_cannot_be_disabled(self) -> CapabilitiesSection:
        for key in CORE_CAPABILITIES:
            entry = getattr(self, key)
            if not entry.enabled:
                raise ValueError(
                    f"capabilities.{key} is a mandatory core capability and cannot be disabled"
                )
        return self

    def explicitly_enabled(self) -> set[str]:
        """Capability keys the user turned on (core included; database only if
        explicitly requested - implicit enablement is resolved by the registry)."""
        enabled = set(CORE_CAPABILITIES)
        for key in SELECTABLE_CAPABILITIES:
            entry = getattr(self, key)
            if entry is not None and entry.enabled:
                enabled.add(key)
        return enabled


class ZoneSettings(_StrictModel):
    retention_days: int = 365

    @field_validator("retention_days")
    @classmethod
    def _validate_retention(cls, v: int) -> int:
        if v < -1 or v == 0:
            raise ValueError("retention_days must be -1 (immutable/forever) or a positive int")
        return v


class StorageZonesSettings(_StrictModel):
    bronze: ZoneSettings = Field(default_factory=lambda: ZoneSettings(retention_days=-1))
    silver: ZoneSettings = Field(default_factory=lambda: ZoneSettings(retention_days=365))
    gold: ZoneSettings = Field(default_factory=lambda: ZoneSettings(retention_days=365))

    @model_validator(mode="after")
    def _bronze_is_immutable(self) -> StorageZonesSettings:
        # Constitution Principle III: Bronze is raw/immutable.
        if self.bronze.retention_days != -1:
            raise ValueError("storage.zones.bronze.retention_days must be -1 (immutable/forever)")
        return self


class StorageSection(_StrictModel):
    table_format: Literal["iceberg"] = "iceberg"
    zones: StorageZonesSettings = Field(default_factory=StorageZonesSettings)


class AtRestEncryption(_StrictModel):
    kms_key_ref: str
    algorithm: Literal["AES-256"] = "AES-256"

    @field_validator("kms_key_ref")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("encryption.at_rest.kms_key_ref must be a non-empty secretRef")
        return v


class InTransitEncryption(_StrictModel):
    min_tls: Literal["1.2", "1.3"] = "1.2"


class EncryptionSection(_StrictModel):
    at_rest: AtRestEncryption
    in_transit: InTransitEncryption = Field(default_factory=InTransitEncryption)


class NetworkingSection(_StrictModel):
    isolation: Isolation = "private"
    cidr: str | None = None

    @field_validator("cidr")
    @classmethod
    def _validate_cidr(cls, v: str | None) -> str | None:
        if v is None:
            return None
        try:
            ipaddress.ip_network(v, strict=False)
        except ValueError as exc:
            raise ValueError(f"networking.cidr is not a valid CIDR block: {exc}") from exc
        return v

    # NOTE: "cidr required when isolation != public" is a *semantic* rule
    # (validation contract rule set, enforced by config/validation.py T028
    # alongside region/dependency/production checks) - not structural.


class SecretsSection(_StrictModel):
    backend: Literal["cloud_native", "aws_secrets_manager", "gcp_secret_manager"] = "cloud_native"
    refs: dict[str, str] = Field(default_factory=dict)


class ObservabilitySection(_StrictModel):
    tracing: Literal["opentelemetry"] = "opentelemetry"
    log_retention_days: int = Field(default=90, ge=1)


class ApprovalSection(_StrictModel):
    ref: str
    approved_by: str

    @field_validator("ref", "approved_by")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("approval fields must not be empty")
        return v


class PlatformConfig(_StrictModel):
    """Declarative platform configuration (contracts/platform-config-schema.md).

    Contains no plaintext secrets - only ``secretRef`` pointers (SC-006,
    enforced by the secret-scan pass in ``config/secret_scan.py``).
    """

    apiVersion: Literal[API_VERSION]  # noqa: N815 - contract field name
    kind: Literal[KIND]
    platform: PlatformSection
    capabilities: CapabilitiesSection
    storage: StorageSection = Field(default_factory=StorageSection)
    encryption: EncryptionSection | None = None
    networking: NetworkingSection = Field(default_factory=NetworkingSection)
    secrets: SecretsSection = Field(default_factory=SecretsSection)
    observability: ObservabilitySection = Field(default_factory=ObservabilitySection)
    approval: ApprovalSection | None = None

    @property
    def is_production(self) -> bool:
        return self.platform.environment == "production"
