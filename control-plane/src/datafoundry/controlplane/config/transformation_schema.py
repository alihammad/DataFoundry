"""Transformation definition schema (feature 003, T007).

Strict Pydantic model per contracts/transformation-schema.md: unknown fields
rejected, ``source_layer`` one layer below ``target_layer``, type-specific
``logic``, secret-scanned on every write (SC-007).
"""

from __future__ import annotations

from typing import Any, Literal

from datafoundry.controlplane.config.secret_scan import SecretFinding, scan_value
from pydantic import BaseModel, ConfigDict, Field, model_validator

Layer = Literal["bronze", "silver", "gold"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CleansingOp(_StrictModel):
    column: str
    op: Literal["trim", "coerce_type", "lower", "upper", "strip_nulls"]
    to: str | None = None


class StandardisationOp(_StrictModel):
    column: str
    op: Literal["upper", "lower", "trim"]


class SchemaEnforcement(_StrictModel):
    type: str
    nullable: bool = True


class SilverLogic(_StrictModel):
    type: Literal["silver"]
    cleansing: list[CleansingOp] = Field(default_factory=list)
    standardisation: list[StandardisationOp] = Field(default_factory=list)
    schema_enforcement: dict[str, SchemaEnforcement] = Field(default_factory=dict)


class Measure(_StrictModel):
    name: str
    op: Literal["sum", "count", "avg", "min", "max"]
    column: str | None = None


class Reconciliation(_StrictModel):
    sql: str
    tolerance_pct: float = Field(default=0.0, ge=0)


class GoldLogic(_StrictModel):
    type: Literal["gold"]
    aggregation: dict[str, Any] = Field(default_factory=dict)
    reconciliation: Reconciliation | None = None


class TransformationDefinition(_StrictModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9_-]{2,62}$")
    source_layer: Layer
    target_layer: Layer
    dedup_keys: list[str] = Field(default_factory=list)
    reconciliation_tolerance: float | None = Field(default=None, ge=0)
    logic: SilverLogic | GoldLogic
    git_ref: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _validate_layers(self) -> TransformationDefinition:
        order = {"bronze": 0, "silver": 1, "gold": 2}
        if order[self.target_layer] - order[self.source_layer] != 1:
            raise ValueError(
                f"source_layer '{self.source_layer}' must be one layer below "
                f"target_layer '{self.target_layer}'"
            )
        return self


class TransformationConfigError(Exception):
    """Raised when a transformation definition fails validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_transformation_definition(
    data: dict[str, Any], *, secret_scan: bool = True
) -> TransformationDefinition:
    """Validate a transformation definition, collecting ALL errors at once.

    Structural (Pydantic) errors plus the secret-scan result are combined into
    a single :class:`TransformationConfigError` (contract rule 5, SC-007).
    """
    errors: list[str] = []
    try:
        model = TransformationDefinition.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        errors.extend(_format_pydantic(exc))
        return _raise_or_return(errors)

    if secret_scan:
        findings = list(scan_value(data, "$"))
        errors.extend(_format_findings(findings))
    if errors:
        raise TransformationConfigError(errors)
    return model


def _raise_or_return(errors: list[str]) -> TransformationDefinition:
    if errors:
        raise TransformationConfigError(errors)
    raise TransformationConfigError(["unknown validation error"])


def _format_findings(findings: list[SecretFinding]) -> list[str]:
    return [f"secret-scan: {f.path} ({f.kind})" for f in findings]


def gitops_provenance(git_ref: str | None) -> dict[str, str]:
    """GitOps provenance marker for a transformation definition (FR-005).

    Mirrors ``config/gitops.py``: git-sourced definitions record
    ``source=git`` + ``git_ref``; API-defined ones record ``source=api``.
    """
    return {"source": "git" if git_ref else "api", "git_ref": git_ref or ""}


def _format_pydantic(exc: Exception) -> list[str]:
    errors = []
    for err in getattr(exc, "errors", lambda: [])():
        loc = ".".join(str(x) for x in err.get("loc", [])) or "$"
        errors.append(f"{loc}: {err.get('msg', 'invalid value')}")
    return errors or [str(exc)]
