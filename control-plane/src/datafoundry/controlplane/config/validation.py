"""Two-stage validation engine (T028, R-07, FR-003, SC-004).

Stage 1 — collect-all schema + semantic rules (never fail-fast):

1. Structural / type / enum / format (Pydantic ``PlatformConfig``, strict).
2. Naming: regex + reserved names (also enforced by the schema; re-checked
   here so *all* problems are reported together).
3. Region-capability matrix: region must exist for the provider and support
   every enabled capability (R-02); remediation lists supported regions.
4. Capability dependency closure (transitive ``depends_on``).
5. Production controls: approval.ref/approved_by, explicit encryption.at_rest,
   isolation != public (FR-010).
6. Secret scan on the raw config (SC-006).
7. Uniqueness pre-check ``(provider, cloud_scope_id, name)`` (FR-013, R-12).

Stage 2 — ``terraform validate``/``plan`` diagnostics translated into the
same ``{path, code, message, remediation}`` shape (used by the ``validate-tf``
deployment step; see engine/orchestrator.py).

Every error carries a remediation hint so a first-time user can self-correct
(SC-007).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import yaml
from datafoundry.controlplane.capabilities.registry import (
    CapabilityRegistry,
    default_registry,
)
from datafoundry.controlplane.config.schema import (
    PLATFORM_NAME_RE,
    RESERVED_NAMES,
    PlatformConfig,
)
from datafoundry.controlplane.config.secret_scan import scan_value
from datafoundry.controlplane.providers.base import ProviderAdapter, ProviderRegistry
from pydantic import ValidationError

#: Error codes (stable API surface — contract tests assert on these).
CODE_SCHEMA = "schema_invalid"
CODE_NAME_INVALID = "name_invalid"
CODE_NAME_RESERVED = "name_reserved"
CODE_REGION_NOT_SUPPORTED = "region_not_supported"
CODE_REGION_CAPABILITY_UNSUPPORTED = "region_capability_unsupported"
CODE_DEPENDENCY_MISSING = "dependency_missing"
CODE_APPROVAL_REQUIRED = "approval_required"
CODE_ENCRYPTION_REQUIRED = "encryption_required"
CODE_ISOLATION_PUBLIC_FORBIDDEN = "isolation_public_in_production"
CODE_SECRET_DETECTED = "secret_detected"  # noqa: S105 — error code, not a secret  # noqa: S105 — error code, not a secret
CODE_NAME_TAKEN = "name_taken"
CODE_TERRAFORM = "terraform_invalid"


@dataclass(frozen=True)
class ValidationErrorItem:
    """One validation error: ``{path, code, message, remediation}``."""

    path: str
    code: str
    message: str
    remediation: str

    def as_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class ValidationResult:
    """Outcome of stage-1 validation (collect-all)."""

    errors: list[ValidationErrorItem] = field(default_factory=list)
    config: PlatformConfig | None = None

    @property
    def valid(self) -> bool:
        return not self.errors

    def error_dicts(self) -> list[dict[str, str]]:
        return [e.as_dict() for e in self.errors]


# -- canonical serialisation (SC-002 reproducibility) --------------------------


def canonical_yaml(config: Mapping[str, Any]) -> str:
    """Canonically-serialised YAML: sorted keys, normalised whitespace."""
    return yaml.safe_dump(dict(config), sort_keys=True, default_flow_style=False)


def config_hash(config: Mapping[str, Any]) -> str:
    """SHA-256 of the canonical YAML (determinism contract, SC-002)."""
    return hashlib.sha256(canonical_yaml(config).encode()).hexdigest()


# -- stage 1 --------------------------------------------------------------------


def _pydantic_to_items(exc: ValidationError) -> list[ValidationErrorItem]:
    items: list[ValidationErrorItem] = []
    for err in exc.errors():
        path = ".".join(str(loc) for loc in err["loc"]) or "$"
        ctx = err.get("ctx") or {}
        message = str(ctx.get("error") or err.get("msg", "invalid value"))
        remediation = "Correct the value per contracts/platform-config-schema.md"
        if err.get("type") == "extra_forbidden":
            remediation = "Remove the unknown field (schema is strict)"
        elif err.get("type") == "missing":
            remediation = "Provide the required field"
        items.append(
            ValidationErrorItem(
                path=path, code=CODE_SCHEMA, message=message, remediation=remediation
            )
        )
    return items


def validate_platform_config(
    raw: Mapping[str, Any] | str,
    *,
    providers: ProviderRegistry,
    registry: CapabilityRegistry | None = None,
    existing_names: Mapping[str, set[str]] | None = None,
    cloud_scope_id: str | None = None,
) -> ValidationResult:
    """Run every stage-1 rule and collect ALL violations (never fail-fast).

    ``raw`` is parsed YAML (mapping) or YAML text. ``existing_names`` maps
    ``"{provider}:{cloud_scope_id}"`` -> registered platform names for the
    uniqueness pre-check (rule 8); the API layer supplies DB + live-cloud
    state (R-12).
    """
    registry = registry or default_registry
    result = ValidationResult()

    parsed: Any = raw
    if isinstance(raw, str):
        try:
            parsed = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            result.errors.append(
                ValidationErrorItem(
                    path="$",
                    code=CODE_SCHEMA,
                    message=f"YAML parse error: {exc}",
                    remediation="Fix the YAML syntax",
                )
            )
            return result
    if not isinstance(parsed, Mapping):
        result.errors.append(
            ValidationErrorItem(
                path="$",
                code=CODE_SCHEMA,
                message="Configuration must be a YAML mapping",
                remediation="Provide a PlatformConfig document",
            )
        )
        return result

    # Rule 7: secret scan on the raw structure (before/independent of schema).
    for finding in scan_value(dict(parsed), "$"):
        result.errors.append(
            ValidationErrorItem(
                path=finding.path.lstrip("$.").replace("$", ""),
                code=CODE_SECRET_DETECTED,
                message=finding.message,
                remediation=(
                    "Remove the plaintext value; reference it via a secretRef "
                    "(secrets.refs) instead (SC-006)"
                ),
            )
        )

    # Rules 1-2: structural / type / enum / format via the strict schema.
    config: PlatformConfig | None = None
    try:
        config = PlatformConfig.model_validate(dict(parsed))
        result.config = config
    except ValidationError as exc:
        result.errors.extend(_pydantic_to_items(exc))

    # Rule 3: naming (re-checked so it is reported alongside everything else).
    platform_section = parsed.get("platform")
    name = platform_section.get("name") if isinstance(platform_section, Mapping) else None
    if isinstance(name, str):
        if not PLATFORM_NAME_RE.match(name):
            result.errors.append(
                ValidationErrorItem(
                    path="platform.name",
                    code=CODE_NAME_INVALID,
                    message=f"platform.name '{name}' does not match ^[a-z][a-z0-9-]{{2,62}}$",
                    remediation=(
                        "Use 3-63 chars: lowercase letter first, then lowercase "
                        "letters, digits or hyphens"
                    ),
                )
            )
        if name in RESERVED_NAMES:
            result.errors.append(
                ValidationErrorItem(
                    path="platform.name",
                    code=CODE_NAME_RESERVED,
                    message=f"platform.name '{name}' is reserved",
                    remediation="Choose a different platform name",
                )
            )

    if config is None:
        return result  # semantic rules need a parsed config

    provider = config.platform.provider
    region = config.platform.region

    # Region / capability matrix (rule 4) — needs a known provider adapter.
    adapter: ProviderAdapter | None = None
    try:
        adapter = providers.get(provider)
    except KeyError:  # pragma: no cover - schema Literal prevents this
        result.errors.append(
            ValidationErrorItem(
                path="platform.provider",
                code=CODE_SCHEMA,
                message=f"unknown provider '{provider}'",
                remediation="Use one of: aws, gcp",
            )
        )

    enabled_explicit = config.capabilities.explicitly_enabled()
    enabled = registry.resolve_enabled(enabled_explicit)

    if adapter is not None:
        known_regions = adapter.regions()
        if region not in known_regions:
            result.errors.append(
                ValidationErrorItem(
                    path="platform.region",
                    code=CODE_REGION_NOT_SUPPORTED,
                    message=f"Region {region} does not exist for provider '{provider}'",
                    remediation=f"Choose one of: {', '.join(known_regions)}",
                )
            )
        else:
            for key in sorted(enabled):
                if not adapter.region_supports(region, key):
                    supported = adapter.regions_for_capability(key)
                    result.errors.append(
                        ValidationErrorItem(
                            path="platform.region",
                            code=CODE_REGION_CAPABILITY_UNSUPPORTED,
                            message=(f"Region {region} does not support capability '{key}'"),
                            remediation=f"Choose one of: {', '.join(supported)}",
                        )
                    )

    # Rule 5: capability dependency closure. Implicit capabilities (database)
    # are auto-enabled by the registry, so they are never "missing".
    for capability_key, missing_dep in registry.missing_dependencies(enabled_explicit):
        dep_capability = registry.capabilities.get(missing_dep)
        if dep_capability is not None and dep_capability.implicit:
            continue
        result.errors.append(
            ValidationErrorItem(
                path=f"capabilities.{capability_key}",
                code=CODE_DEPENDENCY_MISSING,
                message=f"{capability_key} requires {missing_dep}",
                remediation=(f"Enable '{missing_dep}' or disable '{capability_key}'"),
            )
        )

    # Rule 6: production controls (FR-010).
    if config.is_production:
        if config.approval is None or not (
            config.approval.ref.strip() and config.approval.approved_by.strip()
        ):
            result.errors.append(
                ValidationErrorItem(
                    path="approval",
                    code=CODE_APPROVAL_REQUIRED,
                    message=(
                        "environment=production requires approval.ref and "
                        "approval.approved_by (FR-010)"
                    ),
                    remediation=(
                        "Add an approval block with the external approval "
                        "ticket ref and approver identity"
                    ),
                )
            )
        if config.encryption is None or not config.encryption.at_rest.kms_key_ref.strip():
            result.errors.append(
                ValidationErrorItem(
                    path="encryption.at_rest",
                    code=CODE_ENCRYPTION_REQUIRED,
                    message=(
                        "environment=production requires an explicit "
                        "encryption.at_rest block with kms_key_ref"
                    ),
                    remediation=(
                        "Add encryption.at_rest.kms_key_ref (a secretRef, never a literal key)"
                    ),
                )
            )
        if config.networking.isolation == "public":
            result.errors.append(
                ValidationErrorItem(
                    path="networking.isolation",
                    code=CODE_ISOLATION_PUBLIC_FORBIDDEN,
                    message="networking.isolation 'public' is forbidden in production",
                    remediation="Use 'private' or 'internal' isolation",
                )
            )

    # Rule 8: uniqueness pre-check (FR-013, R-12).
    if existing_names is not None and cloud_scope_id is not None:
        scope_key = f"{provider}:{cloud_scope_id}"
        if name in existing_names.get(scope_key, set()):
            result.errors.append(
                ValidationErrorItem(
                    path="platform.name",
                    code=CODE_NAME_TAKEN,
                    message=(
                        f"platform name '{name}' is already registered in scope "
                        f"{provider}/{cloud_scope_id}"
                    ),
                    remediation="Choose a different name or target another cloud scope",
                )
            )

    return result


# -- stage 2: terraform diagnostics translation (R-07) ---------------------------


def translate_terraform_errors(events: list[dict[str, Any]]) -> list[ValidationErrorItem]:
    """Translate ``terraform validate``/``plan`` -json diagnostics into the
    contract error shape so stage-2 failures are reported like stage-1."""
    items: list[ValidationErrorItem] = []
    for event in events:
        if event.get("type") != "diagnostic":
            continue
        diag = event.get("diagnostic") or {}
        if diag.get("severity") != "error":
            continue
        range_ = diag.get("range") or {}
        path = range_.get("filename") or "terraform"
        block = (range_.get("snippet") or "").strip().splitlines()
        summary = diag.get("summary", "terraform error")
        detail = diag.get("detail", "")
        items.append(
            ValidationErrorItem(
                path=path,
                code=CODE_TERRAFORM,
                message=f"{summary}: {detail}" if detail else summary,
                remediation=(
                    block[0]
                    if block
                    else (
                        "Fix the generated Terraform configuration (see engine/generator.py inputs)"
                    )
                ),
            )
        )
    return items
