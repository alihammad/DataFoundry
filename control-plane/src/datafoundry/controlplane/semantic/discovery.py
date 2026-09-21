"""Semantic catalog discovery (feature 006, T035).

Search business terms; certified vs draft distinction; surface
definition/owner/quality_score/freshness/lineage/consuming_teams (FR-011).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from datafoundry.controlplane.db.models import (
    CertificationState,
    ConsumerRegistration,
    Metric,
    SemanticModel,
)
from sqlalchemy import or_, select
from sqlalchemy.orm import Session


@dataclass
class DiscoveryItem:
    """One metric surfaced by a discovery search (FR-011)."""

    metric_id: uuid.UUID
    name: str
    business_definition: str
    owner_identity: str
    quality_score: float | None
    freshness: str | None
    lineage: dict[str, Any]
    certification_state: str
    consuming_teams: list[str]


def search_business_terms(
    session: Session,
    *,
    query: str,
    include_drafts: bool = False,
) -> list[DiscoveryItem]:
    """Search the catalog for a business term (FR-011, US4).

    Matches the metric name or business definition (case-insensitive
    substring). Certified (published) definitions are surfaced; drafts are
    hidden from general users unless ``include_drafts`` is set (US4-AC2).
    """
    terms = [t for t in query.split() if t]
    filters = []
    for term in terms:
        like = f"%{term}%"
        filters.append(
            or_(
                Metric.name.ilike(like),
                Metric.business_definition.ilike(like),
            )
        )
    stmt = select(Metric)
    if filters:
        stmt = stmt.where(or_(*filters))
    metrics = session.scalars(stmt).all()

    items: list[DiscoveryItem] = []
    for metric in metrics:
        model = session.get(SemanticModel, metric.model_id)
        if model is None:
            continue
        if model.certification_state != CertificationState.published and not include_drafts:
            continue
        items.append(
            DiscoveryItem(
                metric_id=metric.id,
                name=metric.name,
                business_definition=metric.business_definition,
                owner_identity=metric.owner_identity,
                quality_score=metric.quality_score,
                freshness=metric.freshness.isoformat() if metric.freshness else None,
                lineage={"model_id": str(model.id), "domain": model.domain},
                certification_state=model.certification_state.value,
                consuming_teams=_consuming_teams(session, metric.id),
            )
        )
    return items


def _consuming_teams(session: Session, metric_id: uuid.UUID) -> list[str]:
    """Teams/paths registered as consumers of a metric (FR-005, FR-010)."""
    rows = session.scalars(
        select(ConsumerRegistration).where(ConsumerRegistration.metric_id == metric_id)
    ).all()
    return [r.consumer_identity for r in rows]
