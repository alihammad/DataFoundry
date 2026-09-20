"""Semantic model + semantic test Pydantic v2 schemas (T007/T008).

Source of truth for contracts/semantic-model-schema.md and
contracts/semantic-test-schema.md. Strict: unknown fields rejected at every
level, no implicit type coercion.

Semantic model validation rules (all errors at once):
1. Schema conformance (strict Pydantic model).
2. Business-term names unique within the domain (FR-009).
3. Metric formula compiles to a valid query over its bound datasets (R-02).
4. Dimension/measure/relationship references resolve within the model.
5. Secret-scan passes on the whole config (SC-007).

Semantic test validation rules:
1. Schema conformance (strict Pydantic model).
2. Test names unique within the model.
3. Parameters valid for the category (FR-004).
4. Secret-scan passes on the whole config (SC-007).
"""

from __future__ import annotations

from typing import Any, Literal

from datafoundry.controlplane.config.secret_scan import (
    SecretFinding,
    scan_value,
    scan_yaml_text,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ProtectionStatus = Literal["public", "internal", "confidential", "restricted", "highly_restricted"]
JoinType = Literal["inner", "left", "right", "full"]
Aggregation = Literal["sum", "count", "avg", "min", "max", "count_distinct"]
TestCategory = Literal["calculation", "reconciliation", "relationship", "filter"]

_STRICT = ConfigDict(strict=True, extra="forbid")


class _StrictModel(BaseModel):
    model_config = _STRICT


# -- semantic model schema (T007) ---------------------------------------------


class MetricFormula(_StrictModel):
    """A metric's declarative formula (measure + aggregation + filter)."""

    measure: str
    aggregation: Aggregation
    filter: dict[str, Any] | None = None


class MetricSpec(_StrictModel):
    name: str = Field(min_length=1, max_length=63)
    business_definition: str = Field(min_length=1)
    formula: MetricFormula
    dimensions: list[str] = Field(min_length=1)
    bound_datasets: list[str] = Field(min_length=1)
    owner: str = Field(min_length=1, max_length=256)


class DimensionSpec(_StrictModel):
    name: str = Field(min_length=1, max_length=63)
    members: list[str] = Field(min_length=1)
    protection_status: ProtectionStatus


class MeasureSpec(_StrictModel):
    name: str = Field(min_length=1, max_length=63)
    dataset: str = Field(min_length=1)
    column: str = Field(min_length=1, max_length=63)
    data_type: str = Field(min_length=1, max_length=63)


class RelationshipSpec(_StrictModel):
    name: str = Field(min_length=1, max_length=63)
    left_dataset: str = Field(min_length=1)
    right_dataset: str = Field(min_length=1)
    join_key: str = Field(min_length=1, max_length=63)
    join_type: JoinType


class SemanticModelDefinition(_StrictModel):
    domain: str = Field(min_length=1, max_length=63)
    metrics: list[MetricSpec] = Field(min_length=1)
    dimensions: list[DimensionSpec] = Field(min_length=1)
    measures: list[MeasureSpec] = Field(min_length=1)
    relationships: list[RelationshipSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_model(self) -> SemanticModelDefinition:
        # Rule 2: business-term names unique within the domain (FR-009).
        for field_name in ("metrics", "dimensions", "measures", "relationships"):
            names = [item.name for item in getattr(self, field_name)]
            if len(names) != len(set(names)):
                raise ValueError(f"{field_name} names must be unique within the domain")
        # Rule 4: references resolve within the model.
        measure_names = {m.name for m in self.measures}
        dimension_names = {d.name for d in self.dimensions}
        dataset_names = (
            {m.dataset for m in self.measures}
            | {r.left_dataset for r in self.relationships}
            | {r.right_dataset for r in self.relationships}
        )
        for metric in self.metrics:
            if metric.formula.measure not in measure_names:
                raise ValueError(
                    f"metric '{metric.name}' references unknown measure '{metric.formula.measure}'"
                )
            unknown_dims = set(metric.dimensions) - dimension_names
            if unknown_dims:
                raise ValueError(
                    f"metric '{metric.name}' references unknown dimension(s): "
                    f"{', '.join(sorted(unknown_dims))}"
                )
            unknown_datasets = set(metric.bound_datasets) - dataset_names
            if unknown_datasets:
                raise ValueError(
                    f"metric '{metric.name}' references unknown dataset(s): "
                    f"{', '.join(sorted(unknown_datasets))}"
                )
        return self


# -- semantic test schema (T008) ----------------------------------------------


class SemanticTestSpec(_StrictModel):
    name: str = Field(min_length=1, max_length=63)
    category: TestCategory
    parameters: dict[str, Any] = Field(default_factory=dict)


class SemanticTestDefinition(_StrictModel):
    tests: list[SemanticTestSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_tests(self) -> SemanticTestDefinition:
        # Rule 2: test names unique within the model.
        names = [t.name for t in self.tests]
        if len(names) != len(set(names)):
            raise ValueError("test names must be unique within the model")
        # Rule 3: parameters valid for the category (FR-004).
        for test in self.tests:
            required = CATEGORY_REQUIRED_PARAMETERS.get(test.category, ())
            missing = [key for key in required if key not in test.parameters]
            if missing:
                raise ValueError(
                    f"test '{test.name}' of category '{test.category}' requires "
                    f"parameter(s): {', '.join(missing)}"
                )
        return self


#: Category -> required parameter keys (semantic-test-schema.md rule 3).
CATEGORY_REQUIRED_PARAMETERS: dict[str, tuple[str, ...]] = {
    "calculation": ("reference_data", "expected_value"),
    "reconciliation": ("source_dataset",),
    "relationship": ("relationship", "max_fanout"),
    "filter": ("filter", "expected_count"),
}


class SemanticConfigError(ValueError):
    """Raised when a semantic config fails validation (structural or secret-scan)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_semantic_model(
    data: dict[str, Any],
    *,
    secret_scan: bool = True,
    yaml_text: str | None = None,
) -> SemanticModelDefinition:
    """Validate a parsed semantic-model mapping, returning the model.

    Collects ALL structural errors (Pydantic) plus the secret-scan result into
    a single :class:`SemanticConfigError` (contract rule 5, SC-007).
    """
    errors: list[str] = []
    try:
        model = SemanticModelDefinition.model_validate(data)
    except Exception as exc:
        errors.extend(_flatten_validation_errors(exc))
    if secret_scan:
        findings = list(scan_value(data, "$"))
        if yaml_text is not None:
            findings.extend(scan_yaml_text(yaml_text))
        if findings:
            errors.extend(_format_findings(findings))
    if errors:
        raise SemanticConfigError(errors)
    return model


def validate_semantic_tests(
    data: dict[str, Any],
    *,
    secret_scan: bool = True,
    yaml_text: str | None = None,
) -> SemanticTestDefinition:
    """Validate a parsed semantic-test mapping, returning the model."""
    errors: list[str] = []
    try:
        model = SemanticTestDefinition.model_validate(data)
    except Exception as exc:
        errors.extend(_flatten_validation_errors(exc))
    if secret_scan:
        findings = list(scan_value(data, "$"))
        if yaml_text is not None:
            findings.extend(scan_yaml_text(yaml_text))
        if findings:
            errors.extend(_format_findings(findings))
    if errors:
        raise SemanticConfigError(errors)
    return model


def _flatten_validation_errors(exc: Exception) -> list[str]:
    """Flatten a Pydantic ValidationError into human-readable messages."""
    if isinstance(exc, ValidationError):
        return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
    return [str(exc)]


def _format_findings(findings: list[SecretFinding]) -> list[str]:
    return [f"secret-scan: {f.path} ({f.kind})" for f in findings]
