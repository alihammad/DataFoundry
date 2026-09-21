"""API router: metrics (T019, contracts/semantic-api.md §2).

- ``POST /semantic/models/{id}/metrics`` — define a metric (FR-001/FR-006):
  201 metric_id; 422 invalid formula/duplicate term/secret-scan.
- ``GET /semantic/metrics/{id}`` — describe a metric (US1-AC3, FR-006).
- ``POST /semantic/metrics/{id}/query`` — query a metric (FR-002/007/008/012):
  200 value + provenance; 403 unauthorised; 409 quality-failed; 410 deprecated.
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db, get_semantic_gateway
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ForbiddenError,
    GoneError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.semantic_schema import (
    MetricFormula,
)
from datafoundry.controlplane.db.models import (
    CertificationState,
    Metric,
    QualityState,
    QueryResultVersion,
    SemanticModel,
)
from datafoundry.controlplane.semantic.compute.engine import (
    MetricCompilationError,
    compute_metric,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["metrics"])


class MetricDefined(BaseModel):
    metric_id: uuid.UUID


class MetricDetail(BaseModel):
    metric_id: uuid.UUID
    name: str
    business_definition: str
    formula: dict[str, Any]
    dimensions: list[str]
    bound_datasets: list[str]
    owner_identity: str
    quality_score: float | None
    freshness: str | None
    lineage: dict[str, Any]
    certification_state: str
    version: int


class MetricQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimensions: list[str] = []
    filters: dict[str, Any] = {}
    as_of: str | None = None


class MetricQueryResponse(BaseModel):
    metric_id: uuid.UUID
    value: float | int
    dimensions: dict[str, Any]
    dimension_values: list[dict[str, Any]] = []
    definition_version: int
    dataset_versions: dict[str, Any]
    freshness: str | None
    quality_state: str
    deprecation_notice: str | None


def _get_metric(session: Session, metric_id: uuid.UUID) -> Metric:
    metric = session.get(Metric, metric_id)
    if metric is None:
        raise NotFoundError(f"no metric with id {metric_id}")
    return metric


@router.post("/semantic/models/{model_id}/metrics", status_code=201, response_model=MetricDefined)
def define_metric(
    model_id: uuid.UUID,
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> MetricDefined:
    """Define a metric (FR-001, FR-006)."""
    model = session.get(SemanticModel, model_id)
    if model is None:
        raise NotFoundError(f"no semantic model with id {model_id}")

    # Validate the metric definition against the model's schema.
    try:
        formula = MetricFormula.model_validate(body.get("formula", {}))
    except Exception as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "formula",
                    "code": "invalid_value",
                    "message": str(exc),
                    "remediation": "Correct the metric formula",
                }
            ]
        ) from exc

    # Duplicate business term within the model (FR-009).
    existing = session.execute(
        select(Metric).where(Metric.model_id == model.id, Metric.name == body.get("name"))
    ).scalar_one_or_none()
    if existing is not None:
        raise ConfigValidationError(
            [
                {
                    "path": "name",
                    "code": "duplicate",
                    "message": f"metric '{body.get('name')}' already exists in this model",
                    "remediation": "Use a unique business term",
                }
            ]
        )

    metric = Metric(
        model_id=model.id,
        name=body["name"],
        business_definition=body["business_definition"],
        formula=formula.model_dump(),
        dimensions=body.get("dimensions", []),
        bound_datasets=body.get("bound_datasets", []),
        owner_identity=body.get("owner", caller.identity),
    )
    session.add(metric)
    session.flush()
    return MetricDefined(metric_id=metric.id)


@router.get("/semantic/metrics/{metric_id}", response_model=MetricDetail)
def describe_metric(
    metric_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> MetricDetail:
    """Describe a metric (US1-AC3, FR-006)."""
    metric = _get_metric(session, metric_id)
    model = session.get(SemanticModel, metric.model_id)
    return MetricDetail(
        metric_id=metric.id,
        name=metric.name,
        business_definition=metric.business_definition,
        formula=dict(metric.formula or {}),
        dimensions=list(metric.dimensions or []),
        bound_datasets=list(metric.bound_datasets or []),
        owner_identity=metric.owner_identity,
        quality_score=metric.quality_score,
        freshness=metric.freshness.isoformat() if metric.freshness else None,
        lineage={"model_id": str(model.id), "domain": model.domain},
        certification_state=model.certification_state.value if model else "draft",
        version=model.version if model else 1,
    )


@router.post("/semantic/metrics/{metric_id}/query", response_model=MetricQueryResponse)
def query_metric(
    metric_id: uuid.UUID,
    body: MetricQueryRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    semantic_gateway: Any = Depends(get_semantic_gateway),
) -> MetricQueryResponse:
    """Query a metric (FR-002, FR-007, FR-008, FR-012)."""
    metric = _get_metric(session, metric_id)
    model = session.get(SemanticModel, metric.model_id)

    # Deprecated past availability -> 410 (FR-010).
    if model is not None and model.certification_state == CertificationState.deprecated:
        raise GoneError(f"metric '{metric.name}' is deprecated and no longer available (FR-010)")

    formula = metric.formula or {}
    measure_name = formula.get("measure")
    aggregation = formula.get("aggregation", "sum")
    filter_spec = formula.get("filter")

    # Resolve the measure's source dataset + column.
    from datafoundry.controlplane.db.models import Measure

    measure = session.execute(
        select(Measure).where(Measure.model_id == metric.model_id, Measure.name == measure_name)
    ).scalar_one_or_none()
    if measure is None:
        raise ConfigValidationError(
            [
                {
                    "path": "formula.measure",
                    "code": "invalid_value",
                    "message": f"unknown measure '{measure_name}'",
                    "remediation": "Reference a measure defined in the model",
                }
            ]
        )

    from datafoundry.controlplane.db.models import Dataset

    dataset = session.get(Dataset, measure.dataset_id)
    dataset_name = dataset.name if dataset else measure.dataset_id

    # US3: enforce role-based visibility + column/row protection (FR-007).
    from datafoundry.controlplane.semantic.access import enforce_metric_access

    access = enforce_metric_access(
        session,
        caller_identity=caller.identity,
        caller_roles=list(caller.roles),
        metric=metric,
        dataset=dataset,
        gateway=semantic_gateway,
    )

    try:
        result = compute_metric(
            gateway=semantic_gateway,
            dataset=dataset_name,
            layer=dataset.layer.value if dataset else "gold",
            measure_column=measure.column,
            aggregation=aggregation,
            filter_spec=filter_spec,
            dimensions=body.dimensions,
            definition_version=model.version if model else 1,
            row_filters=access.row_filters,
            protected_columns=access.protected_columns,
        )
    except MetricCompilationError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "formula",
                    "code": "invalid_value",
                    "message": str(exc),
                    "remediation": "Correct the metric formula",
                }
            ]
        ) from exc

    # Quality-failed data -> 409 (FR-008).
    if result.quality_state == "failed":
        raise ForbiddenError(
            ["quality"],
            detail="underlying data failed its quality gate (FR-008)",
        )

    # Record the definition version with the result (FR-012).
    session.add(
        QueryResultVersion(
            metric_id=metric.id,
            model_version=result.definition_version,
            dataset_versions=result.dataset_versions,
            freshness=None,
            quality_state=QualityState(result.quality_state),
        )
    )
    AuditService(session).semantic_metric_queried(
        actor=caller.identity, metric_id=metric.id, model_version=result.definition_version
    )
    session.flush()
    return MetricQueryResponse(
        metric_id=metric.id,
        value=result.value,
        dimensions={},
        dimension_values=result.dimension_values,
        definition_version=result.definition_version,
        dataset_versions=result.dataset_versions,
        freshness=result.freshness,
        quality_state=result.quality_state,
        deprecation_notice=None,
    )


class MetricDeprecateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    successor_metric_id: uuid.UUID | None = None
    availability_period_days: int = 30


class MetricDeprecated(BaseModel):
    metric_id: uuid.UUID
    successor_metric_id: uuid.UUID | None
    availability_period_days: int


@router.post("/semantic/metrics/{metric_id}/deprecate", response_model=MetricDeprecated)
def deprecate_metric_endpoint(
    metric_id: uuid.UUID,
    body: MetricDeprecateRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> MetricDeprecated:
    """Deprecate a metric with an optional successor (FR-010)."""
    from datafoundry.controlplane.semantic.deprecation import (
        DeprecationError,
        deprecate_metric,
    )

    try:
        result = deprecate_metric(
            session,
            metric_id=metric_id,
            successor_metric_id=body.successor_metric_id,
            availability_period_days=body.availability_period_days,
        )
    except DeprecationError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "$",
                    "code": "invalid_value",
                    "message": str(exc),
                    "remediation": "Reference an existing metric as successor",
                }
            ]
        ) from exc
    AuditService(session).semantic_metric_deprecated(
        actor=caller.identity,
        metric_id=metric_id,
        successor_metric_id=body.successor_metric_id,
    )
    session.flush()
    return MetricDeprecated(
        metric_id=result.metric_id,
        successor_metric_id=result.successor_metric_id,
        availability_period_days=result.availability_period_days,
    )
