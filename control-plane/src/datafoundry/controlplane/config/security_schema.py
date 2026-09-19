"""Protection policy schema (feature 005, T007).

Strict Pydantic model per contracts/protection-policy-schema.md: unknown
fields rejected, classification/mechanism enums, key_ref required for
encrypt/tokenise, detokenise_roles subset of authorised_roles, secret-scanned
on every write (SC-003).
"""

from __future__ import annotations

from typing import Any, Literal

from datafoundry.controlplane.config.secret_scan import SecretFinding, scan_value
from pydantic import BaseModel, ConfigDict, Field, model_validator

SecurityLevel = Literal["public", "internal", "confidential", "restricted", "highly_restricted"]
Mechanism = Literal["encrypt", "tokenise", "mask", "hash", "redact", "pseudonymise"]

_MECHANISMS_REQUIRING_KEY = {"encrypt", "tokenise"}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProtectionPolicyDefinition(_StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,62}$")
    classification: SecurityLevel
    mechanism: Mechanism
    key_ref_id: str | None = None
    token_service_ref: str | None = None
    authorised_roles: list[str] = Field(min_length=1)
    detokenise_roles: list[str] | None = None
    masking_rule: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_policy(self) -> ProtectionPolicyDefinition:
        if self.mechanism in _MECHANISMS_REQUIRING_KEY and not self.key_ref_id:
            raise ValueError(f"mechanism '{self.mechanism}' requires key_ref_id (FR-008)")
        if self.mechanism == "tokenise" and not self.token_service_ref:
            raise ValueError("mechanism 'tokenise' requires token_service_ref (FR-011)")
        if self.detokenise_roles is not None:
            extra = set(self.detokenise_roles) - set(self.authorised_roles)
            if extra:
                raise ValueError(
                    f"detokenise_roles must be a subset of authorised_roles; "
                    f"not authorised: {sorted(extra)} (FR-012)"
                )
        if self.mechanism != "mask" and self.masking_rule is not None:
            raise ValueError("masking_rule only valid when mechanism is 'mask'")
        return self


class SecurityConfigError(Exception):
    """Raised when a protection policy fails validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_protection_policy(
    data: dict[str, Any], *, secret_scan: bool = True
) -> ProtectionPolicyDefinition:
    """Validate a protection policy, collecting ALL errors at once."""
    errors: list[str] = []
    try:
        model = ProtectionPolicyDefinition.model_validate(data)
    except Exception as exc:
        errors.extend(_format_pydantic(exc))
        if errors:
            raise SecurityConfigError(errors) from exc
        raise SecurityConfigError(["unknown validation error"]) from exc

    if secret_scan:
        findings = list(scan_value(data, "$"))
        errors.extend(_format_findings(findings))
    if errors:
        raise SecurityConfigError(errors)
    return model


def _format_findings(findings: list[SecretFinding]) -> list[str]:
    return [f"secret-scan: {f.path} ({f.kind})" for f in findings]


def _format_pydantic(exc: Exception) -> list[str]:
    errors = []
    for err in getattr(exc, "errors", lambda: [])():
        loc = ".".join(str(x) for x in err.get("loc", [])) or "$"
        errors.append(f"{loc}: {err.get('msg', 'invalid value')}")
    return errors or [str(exc)]
