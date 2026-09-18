"""Dataset registration schema (feature 003, T019).

Strict Pydantic model per contracts/dataset-schema.md: unknown fields
rejected, layer enum, classification enum, secret-scanned on every write
(SC-007).
"""

from __future__ import annotations

from typing import Any, Literal

from datafoundry.controlplane.config.secret_scan import SecretFinding, scan_value
from pydantic import BaseModel, ConfigDict, Field, model_validator

Layer = Literal["bronze", "silver", "gold"]
Classification = Literal["public", "internal", "confidential", "restricted", "highly_restricted"]

_COLUMN_TYPES = {
    "integer",
    "string",
    "float",
    "boolean",
    "timestamp",
    "date",
    "decimal",
    "json",
    "binary",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetDefinition(_StrictModel):
    platform_id: str
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,62}$")
    layer: Layer
    schema_definition: dict[str, dict[str, Any]]
    owner_identity: str
    steward_identity: str | None = None
    domain: str | None = None
    description: str | None = None
    classification: Classification
    refresh_metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_schema_types(self) -> DatasetDefinition:
        for col, spec in self.schema_definition.items():
            col_type = spec.get("type")
            if col_type not in _COLUMN_TYPES:
                raise ValueError(f"schema_definition.{col}.type: unknown column type '{col_type}'")
        return self


class DatasetConfigError(Exception):
    """Raised when a dataset registration fails validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_dataset_definition(
    data: dict[str, Any], *, secret_scan: bool = True
) -> DatasetDefinition:
    """Validate a dataset registration, collecting ALL errors at once."""
    errors: list[str] = []
    try:
        model = DatasetDefinition.model_validate(data)
    except Exception as exc:
        errors.extend(_format_pydantic(exc))
        if errors:
            raise DatasetConfigError(errors) from exc
        raise DatasetConfigError(["unknown validation error"]) from exc

    if secret_scan:
        findings = list(scan_value(data, "$"))
        errors.extend(_format_findings(findings))
    if errors:
        raise DatasetConfigError(errors)
    return model


def _format_findings(findings: list[SecretFinding]) -> list[str]:
    return [f"secret-scan: {f.path} ({f.kind})" for f in findings]


def _format_pydantic(exc: Exception) -> list[str]:
    errors = []
    for err in getattr(exc, "errors", lambda: [])():
        loc = ".".join(str(x) for x in err.get("loc", [])) or "$"
        errors.append(f"{loc}: {err.get('msg', 'invalid value')}")
    return errors or [str(exc)]
