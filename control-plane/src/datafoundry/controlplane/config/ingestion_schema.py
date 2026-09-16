"""Ingestion configuration Pydantic v2 schema (T007).

Source of truth for contracts/source-config-schema.md. Strict: unknown fields
are rejected at every level and no implicit type coercion is applied.

Validation rules (all errors at once, per the contract):
1. Schema conformance (strict Pydantic model).
2. ``source.type`` matches the registered source's type.
3. Every ``incremental`` object declares a valid ``cursor_column``.
4. ``schedule``, if present, is a well-formed interval or cron expression.
5. ``filePattern`` present iff ``object_storage``; ``objects[]`` present iff
   database type.
6. Secret-scan passes on the entire document (no credential values anywhere —
   SC-007).

The schema is cloud-independent YAML (FR-017); the canonical YAML text is
stored on :class:`IngestionConfig.config_yaml` and secret-scanned before
persist.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from datafoundry.controlplane.config.secret_scan import (
    SecretFinding,
    scan_value,
    scan_yaml_text,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

SourceType = Literal["postgres", "sqlserver", "object_storage"]
IngestionMode = Literal["full", "incremental"]
TargetZone = Literal["bronze"]

#: ``^[a-z][a-z0-9-]{2,62}$`` (metadata.name).
_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{2,62}$")

#: Well-formed interval expressions (e.g. "every 15 minutes", "hourly",
#: "daily") or cron expressions (5 fields).
_CRON_RE = re.compile(r"^(\S+\s+){4}\S+$")
_INTERVALS = frozenset({"hourly", "daily", "weekly", "monthly"})

_STRICT = ConfigDict(strict=True, extra="forbid")


class _StrictModel(BaseModel):
    model_config = _STRICT


class SourceObject(_StrictModel):
    """One selected table (database sources)."""

    name: str = Field(min_length=1, max_length=256)
    mode: IngestionMode
    cursor_column: str | None = Field(default=None, max_length=256)


class Metadata(_StrictModel):
    name: str = Field(pattern=_NAME_RE.pattern)
    source: str = Field(min_length=1, max_length=63)


class SourceSpec(_StrictModel):
    type: SourceType
    objects: list[SourceObject] | None = Field(default=None)
    filePattern: str | None = Field(default=None, max_length=256)  # noqa: N815


class Target(_StrictModel):
    zone: TargetZone


class Validation(_StrictModel):
    reconciliation_tolerance: int = Field(default=0, ge=0)
    contract_mode: Literal["enforce", "infer"] = "enforce"


class IngestionConfigSchema(_StrictModel):
    """A full ingestion configuration (contracts/source-config-schema.md)."""

    apiVersion: Literal["datafoundry/v1"]  # noqa: N815
    kind: Literal["IngestionConfig"]
    metadata: Metadata
    source: SourceSpec
    schedule: str | None = Field(default=None, max_length=128)
    target: Target
    validation: Validation = Field(default_factory=Validation)

    @model_validator(mode="after")
    def _validate_ingestion(self) -> IngestionConfigSchema:
        # Rule 3: every incremental object declares a cursor column.
        for obj in self.source.objects or []:
            if obj.mode == "incremental" and not obj.cursor_column:
                raise ValueError(
                    f"object '{obj.name}' is incremental but has no cursor_column"
                )
        # Rule 5: filePattern iff object_storage; objects[] iff database type.
        if self.source.type == "object_storage":
            if not self.source.filePattern:
                raise ValueError("object_storage source requires filePattern")
            if self.source.objects:
                raise ValueError("object_storage source must not declare objects[]")
        else:
            if self.source.filePattern:
                raise ValueError("database source must not declare filePattern")
            if not self.source.objects:
                raise ValueError("database source requires at least one object")
        # Rule 4: schedule well-formed.
        if self.schedule is not None and not _valid_schedule(self.schedule):
            raise ValueError(f"invalid schedule: '{self.schedule}'")
        return self


def _valid_schedule(schedule: str) -> bool:
    """Whether a schedule string is a well-formed interval or cron expression."""
    lowered = schedule.strip().lower()
    if lowered in _INTERVALS:
        return True
    if lowered.startswith("every "):
        return bool(re.match(r"^every \d+ (seconds?|minutes?|hours?|days?)$", lowered))
    return bool(_CRON_RE.match(schedule.strip()))


class IngestionConfigError(ValueError):
    """Raised when an ingestion config fails validation (structural or secret-scan)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_ingestion_config(
    data: dict[str, Any],
    *,
    secret_scan: bool = True,
    yaml_text: str | None = None,
) -> IngestionConfigSchema:
    """Validate a parsed ingestion-config mapping, returning the model.

    Collects ALL structural errors (Pydantic) plus the secret-scan result into
    a single :class:`IngestionConfigError` so the API can return one 422 with
    every problem at once (contract rule 6, SC-007).

    ``yaml_text`` is the canonical YAML document; when provided it is
    secret-scanned too (the parsed ``data`` is always scanned).
    """
    errors: list[str] = []

    try:
        config = IngestionConfigSchema.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        errors.extend(_flatten_validation_errors(exc))

    if secret_scan:
        findings = list(scan_value(data, "$"))
        if yaml_text is not None:
            findings.extend(scan_yaml_text(yaml_text))
        if findings:
            errors.extend(_format_findings(findings))

    if errors:
        raise IngestionConfigError(errors)
    return config


def _flatten_validation_errors(exc: Exception) -> list[str]:
    """Flatten a Pydantic ValidationError into human-readable messages."""
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return [str(exc)]


def _format_findings(findings: list[SecretFinding]) -> list[str]:
    return [f"secret-scan: {f.path} ({f.kind})" for f in findings]


__all__ = [
    "IngestionConfigError",
    "IngestionConfigSchema",
    "SourceObject",
    "validate_ingestion_config",
]
