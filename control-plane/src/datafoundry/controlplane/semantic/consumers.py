"""Semantic consumer registration + notification (feature 006, T037).

Breaking-change + deprecation notification (FR-005/FR-010).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from datafoundry.controlplane.db.models import (
    ConsumerRegistration,
    ConsumptionPath,
    Metric,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("datafoundry.semantic.consumers")


class ConsumerRegistrationError(ValueError):
    """Raised when a consumer registration is invalid."""


@dataclass
class ConsumerRecord:
    """One registered consumer of a metric (FR-005, FR-010)."""

    consumer_identity: str
    consumption_path: str


def register_consumer(
    session: Session,
    *,
    metric_id: uuid.UUID,
    consumer_identity: str,
    consumption_path: str,
) -> ConsumerRegistration:
    """Register a team/path as a consumer of a metric (FR-005, FR-010)."""
    metric = session.get(Metric, metric_id)
    if metric is None:
        raise ConsumerRegistrationError(f"no metric with id {metric_id}")
    try:
        path = ConsumptionPath(consumption_path)
    except ValueError as exc:
        raise ConsumerRegistrationError(f"invalid consumption path '{consumption_path}'") from exc
    existing = session.execute(
        select(ConsumerRegistration).where(
            ConsumerRegistration.metric_id == metric_id,
            ConsumerRegistration.consumer_identity == consumer_identity,
            ConsumerRegistration.consumption_path == path,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    registration = ConsumerRegistration(
        metric_id=metric_id,
        consumer_identity=consumer_identity,
        consumption_path=path,
    )
    session.add(registration)
    session.flush()
    return registration


def list_consumers(session: Session, *, metric_id: uuid.UUID) -> list[ConsumerRecord]:
    """List a metric's registered consumers (FR-005, FR-010)."""
    rows = session.scalars(
        select(ConsumerRegistration).where(ConsumerRegistration.metric_id == metric_id)
    ).all()
    return [
        ConsumerRecord(
            consumer_identity=r.consumer_identity,
            consumption_path=r.consumption_path.value,
        )
        for r in rows
    ]


def notify_consumers(
    session: Session,
    *,
    metric_id: uuid.UUID,
    message: str,
) -> list[str]:
    """Notify a metric's registered consumers (FR-005, FR-010).

    MVP: logs the notification via the structured-logging channel and returns
    the notified consumer identities. Live notification channels are wired
    later.
    """
    consumers = list_consumers(session, metric_id=metric_id)
    identities = [c.consumer_identity for c in consumers]
    for identity in identities:
        logger.info(
            "semantic_consumer_notify metric_id=%s consumer=%s message=%s",
            metric_id,
            identity,
            message,
        )
    return identities
