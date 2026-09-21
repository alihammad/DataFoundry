"""API router: semantic consumers (T037, contracts/semantic-api.md §5).

- ``POST /semantic/metrics/{id}/consumers`` — register a consumer (FR-005):
  201 consumer_id.
- ``GET /semantic/metrics/{id}/consumers`` — list consumers (FR-005/FR-010).
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import ConfigValidationError, NotFoundError
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.db.models import Metric
from datafoundry.controlplane.semantic.consumers import (
    ConsumerRegistrationError,
    list_consumers,
    register_consumer,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

router = APIRouter(tags=["semantic-consumers"])


class ConsumerRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consumer_identity: str
    consumption_path: str


class ConsumerRegistered(BaseModel):
    consumer_id: uuid.UUID


class ConsumerItem(BaseModel):
    consumer_identity: str
    consumption_path: str


class ConsumerList(BaseModel):
    items: list[ConsumerItem]


def _get_metric(session: Session, metric_id: uuid.UUID) -> Metric:
    metric = session.get(Metric, metric_id)
    if metric is None:
        raise NotFoundError(f"no metric with id {metric_id}")
    return metric


@router.post(
    "/semantic/metrics/{metric_id}/consumers",
    status_code=201,
    response_model=ConsumerRegistered,
)
def register_consumer_endpoint(
    metric_id: uuid.UUID,
    body: ConsumerRegisterRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ConsumerRegistered:
    """Register a consumer (FR-005, FR-010)."""
    _get_metric(session, metric_id)
    try:
        registration = register_consumer(
            session,
            metric_id=metric_id,
            consumer_identity=body.consumer_identity,
            consumption_path=body.consumption_path,
        )
    except ConsumerRegistrationError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "$",
                    "code": "invalid_value",
                    "message": str(exc),
                    "remediation": (
                        "Use a valid consumption path (bi|analyst_sql|ai_ml|application)"
                    ),
                }
            ]
        ) from exc
    AuditService(session).semantic_consumer_registered(
        actor=caller.identity,
        metric_id=metric_id,
        consumer_identity=body.consumer_identity,
    )
    session.flush()
    return ConsumerRegistered(consumer_id=registration.id)


@router.get("/semantic/metrics/{metric_id}/consumers", response_model=ConsumerList)
def list_consumers_endpoint(
    metric_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ConsumerList:
    """List a metric's consumers (FR-005, FR-010)."""
    _get_metric(session, metric_id)
    consumers = list_consumers(session, metric_id=metric_id)
    return ConsumerList(
        items=[
            ConsumerItem(
                consumer_identity=c.consumer_identity,
                consumption_path=c.consumption_path,
            )
            for c in consumers
        ]
    )
