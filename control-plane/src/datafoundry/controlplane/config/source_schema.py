"""Source registration schema (T020, contracts/ingestion-api.md §1).

Validates the ``config_ref`` for a data source: host/database/port or location,
with credentials always a ``secretRef`` pointer (never a value — SC-007). The
``secretRef`` name must be a well-formed secret-manager key (no spaces, no
secret material).
"""

from __future__ import annotations

import re
from typing import Any, Literal

from datafoundry.controlplane.config.secret_scan import SecretFinding, scan_value
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SourceType = Literal["postgres", "sqlserver", "object_storage"]

#: ``^[a-z][a-z0-9-]{2,62}$`` (metadata.name / source name).
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")

#: A secret-manager key reference: letters/digits plus ``_``, ``-``, ``.``, ``/``.
_SECRET_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

_STRICT = ConfigDict(strict=True, extra="forbid")


class _StrictModel(BaseModel):
    model_config = _STRICT


class Credentials(_StrictModel):
    secretRef: str = Field(min_length=1, max_length=256)  # noqa: N815


class DatabaseConfig(_StrictModel):
    host: str = Field(min_length=1, max_length=256)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=256)
    credentials: Credentials


class ObjectStorageConfig(_StrictModel):
    location: str = Field(min_length=1, max_length=512)
    format: Literal["csv", "json", "parquet"] = "parquet"


class SourceRegistration(_StrictModel):
    """Request body for ``POST /sources`` (ingestion-api.md §1)."""

    platform_id: str
    name: str = Field(pattern=_NAME_RE.pattern)
    type: SourceType
    config: dict[str, Any]

    @model_validator(mode="after")
    def _validate_config(self) -> SourceRegistration:
        if self.type == "object_storage":
            ObjectStorageConfig.model_validate(self.config)
        else:
            DatabaseConfig.model_validate(self.config)
        return self


class SourceRegistrationError(ValueError):
    """Raised when a source registration fails validation (structural or secret)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_source_registration(data: dict[str, Any]) -> SourceRegistration:
    """Validate a source-registration mapping, collecting ALL errors at once.

    Structural errors (Pydantic) plus the secret-scan result are combined into
    a single :class:`SourceRegistrationError` so the API returns one 422 with
    every problem at once (SC-007).
    """
    errors: list[str] = []

    try:
        registration = SourceRegistration.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        errors.extend(_flatten_validation_errors(exc))

    # Secret-scan on the whole document (SC-007): credentials must be a
    # secretRef pointer, never a literal value.
    findings = list(scan_value(data, "$"))
    if findings:
        errors.extend(_format_findings(findings))

    # secretRef naming rule (ingestion-api.md §1): well-formed key.
    config = data.get("config") or {}
    credentials = config.get("credentials") if isinstance(config, dict) else None
    if isinstance(credentials, dict):
        secret_ref = credentials.get("secretRef")
        if isinstance(secret_ref, str) and not _SECRET_REF_RE.match(secret_ref):
            errors.append(f"config.credentials.secretRef: invalid secretRef name '{secret_ref}'")

    if errors:
        raise SourceRegistrationError(errors)
    return registration


def _flatten_validation_errors(exc: Exception) -> list[str]:
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return [str(exc)]


def _format_findings(findings: list[SecretFinding]) -> list[str]:
    return [f"secret-scan: {f.path} ({f.kind})" for f in findings]


__all__ = [
    "SourceRegistration",
    "SourceRegistrationError",
    "validate_source_registration",
]
