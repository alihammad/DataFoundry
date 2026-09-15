"""Gate configuration Pydantic v2 schema (T007).

Source of truth for contracts/gate-config-schema.md. Strict: unknown fields
are rejected at every level and no implicit type coercion is applied.

Validation rules (all errors at once, per the contract):
1. Schema conformance (strict Pydantic model).
2. At least one test with severity ``critical`` or ``error`` (fail-closed,
   FR-002).
3. Test names unique within the gate.
4. Parameters valid for the category (e.g. ``freshness`` requires
   ``max_staleness_minutes``; ``uniqueness`` requires ``columns``).
5. Secret-scan passes on the whole config (SC-007).

The schema is cloud-independent YAML (FR-018); the canonical YAML text is
stored on :class:`QualityGate.config_yaml` and secret-scanned before persist.
"""

from __future__ import annotations

from typing import Any, Literal

from datafoundry.controlplane.config.secret_scan import (
    SecretFinding,
    scan_value,
    scan_yaml_text,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

Transition = Literal[
    "ingestion_to_bronze",
    "bronze_to_silver",
    "silver_to_gold",
    "gold_to_consumable",
]
Severity = Literal["critical", "error", "warning", "informational"]
Category = Literal[
    "schema",
    "type",
    "nullability",
    "uniqueness",
    "completeness",
    "validity",
    "referential_integrity",
    "reconciliation",
    "freshness",
    "volume",
    "distribution",
    "business_rule",
    "security",
    "contract",
    "transformation",
    "statistical",
]

#: The 17 standard test categories (FR-003).
CATEGORIES: tuple[str, ...] = (
    "schema",
    "type",
    "nullability",
    "uniqueness",
    "completeness",
    "validity",
    "referential_integrity",
    "reconciliation",
    "freshness",
    "volume",
    "distribution",
    "business_rule",
    "security",
    "contract",
    "transformation",
    "statistical",
)

#: Severities that block by default (fail-closed, FR-002/FR-004).
BLOCKING_SEVERITIES = frozenset({"critical", "error"})

#: Category -> required parameter keys (validation rule 4).
CATEGORY_REQUIRED_PARAMETERS: dict[str, tuple[str, ...]] = {
    "schema": ("expected_schema",),
    "type": ("columns",),
    "nullability": ("columns",),
    "uniqueness": ("columns",),
    "completeness": ("columns",),
    "validity": ("columns",),
    "referential_integrity": ("columns", "reference_table", "reference_column"),
    "reconciliation": ("sql",),
    "freshness": ("max_staleness_minutes",),
    "volume": ("min_records",),
    "distribution": ("columns",),
    "business_rule": ("expression",),
    "security": ("columns",),
    "contract": ("contract_version",),
    "transformation": ("expression",),
    "statistical": ("columns",),
}

_STRICT = ConfigDict(strict=True, extra="forbid")


class _StrictModel(BaseModel):
    model_config = _STRICT


class TestSpec(_StrictModel):
    """One test definition inside a gate config."""

    name: str = Field(min_length=1, max_length=63)
    category: Category
    severity: Severity
    parameters: dict[str, Any] = Field(default_factory=dict)


class GateConfig(_StrictModel):
    """A full gate configuration bound to a layer transition (FR-001)."""

    transition: Transition
    environment_overrides: dict[str, dict[str, Severity]] = Field(default_factory=dict)
    tests: list[TestSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_gate(self) -> GateConfig:
        # Rule 2: at least one CRITICAL/ERROR test (fail-closed, FR-002).
        if not any(t.severity in BLOCKING_SEVERITIES for t in self.tests):
            raise ValueError(
                "gate must contain at least one test with severity 'critical' or 'error'"
            )
        # Rule 3: test names unique within the gate.
        names = [t.name for t in self.tests]
        if len(names) != len(set(names)):
            raise ValueError("test names must be unique within the gate")
        # Rule 4: parameters valid for the category.
        for test in self.tests:
            required = CATEGORY_REQUIRED_PARAMETERS.get(test.category, ())
            missing = [key for key in required if key not in test.parameters]
            if missing:
                raise ValueError(
                    f"test '{test.name}' of category '{test.category}' requires "
                    f"parameter(s): {', '.join(missing)}"
                )
        return self


class GateConfigError(ValueError):
    """Raised when a gate config fails validation (structural or secret-scan)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_gate_config(
    data: dict[str, Any],
    *,
    secret_scan: bool = True,
    yaml_text: str | None = None,
) -> GateConfig:
    """Validate a parsed gate-config mapping, returning the model.

    Collects ALL structural errors (Pydantic) plus the secret-scan result into
    a single :class:`GateConfigError` so the API can return one 422 with every
    problem at once (contract rule 5, SC-007).

    ``yaml_text`` is the canonical YAML document; when provided it is
    secret-scanned too (the parsed ``data`` is always scanned).
    """
    errors: list[str] = []

    try:
        config = GateConfig.model_validate(data)
    except Exception as exc:  # pydantic.ValidationError
        errors.extend(_flatten_validation_errors(exc))

    if secret_scan:
        findings = list(scan_value(data, "$"))
        if yaml_text is not None:
            findings.extend(scan_yaml_text(yaml_text))
        if findings:
            errors.extend(_format_findings(findings))

    if errors:
        raise GateConfigError(errors)
    return config


def _flatten_validation_errors(exc: Exception) -> list[str]:
    """Flatten a Pydantic ValidationError into human-readable messages."""
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return [str(exc)]


def _format_findings(findings: list[SecretFinding]) -> list[str]:
    return [f"secret-scan: {f.path} ({f.kind})" for f in findings]


__all__ = [
    "BLOCKING_SEVERITIES",
    "CATEGORIES",
    "CATEGORY_REQUIRED_PARAMETERS",
    "GateConfig",
    "GateConfigError",
    "TestSpec",
    "validate_gate_config",
]
