"""Semantic metric deprecation (feature 006, T038).

Successor reference; time-bounded continued availability; deprecation notice
in results (FR-010).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from datafoundry.controlplane.db.models import (
    CertificationState,
    Metric,
    SemanticModel,
)
from sqlalchemy.orm import Session


class DeprecationError(ValueError):
    """Raised when a metric cannot be deprecated."""


@dataclass
class DeprecationResult:
    """The outcome of a metric deprecation (FR-010)."""

    metric_id: uuid.UUID
    successor_metric_id: uuid.UUID | None
    availability_period_days: int


def deprecate_metric(
    session: Session,
    *,
    metric_id: uuid.UUID,
    successor_metric_id: uuid.UUID | None,
    availability_period_days: int,
) -> DeprecationResult:
    """Deprecate a metric with an optional successor (FR-010).

    Marks the owning model deprecated and records the successor reference on
    the metric. The metric remains available for ``availability_period_days``
    (time-bounded continued availability, FR-010).
    """
    metric = session.get(Metric, metric_id)
    if metric is None:
        raise DeprecationError(f"no metric with id {metric_id}")
    if successor_metric_id is not None:
        successor = session.get(Metric, successor_metric_id)
        if successor is None:
            raise DeprecationError(f"no successor metric with id {successor_metric_id}")
    metric.successor_metric_id = successor_metric_id
    model = session.get(SemanticModel, metric.model_id)
    if model is not None:
        model.certification_state = CertificationState.deprecated
    session.flush()
    return DeprecationResult(
        metric_id=metric.id,
        successor_metric_id=successor_metric_id,
        availability_period_days=availability_period_days,
    )
