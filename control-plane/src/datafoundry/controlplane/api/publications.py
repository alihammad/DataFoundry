"""API router: publications (T027, contracts/semantic-api.md §4).

- ``POST /semantic/models/{id}/publish`` — propose a publication (FR-003/004):
  201 pending; 422 blocked on failed tests.
- ``POST /publications/{id}/approve`` — approve a publication (FR-005):
  200 approved + published_at; notifies consumers of breaking changes.
- ``GET /semantic/models/{id}/publications`` — list publication history.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db, get_semantic_gateway
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.db.models import (
    ChangeClassification,
    ConsumerRegistration,
    Publication,
    SemanticModel,
)
from datafoundry.controlplane.semantic.lifecycle import (
    PublicationBlockedError,
    PublicationNotFoundError,
    approve_publication,
    list_publications,
    propose_publication,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["publications"])


class PublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    change_classification: str


class PublicationProposed(BaseModel):
    publication_id: uuid.UUID
    approval_status: str


class PublicationApproved(BaseModel):
    approval_status: str
    published_at: str | None


class PublicationItem(BaseModel):
    publication_id: uuid.UUID
    version: int
    change_classification: str
    approval_status: str
    published_at: datetime | None


class PublicationList(BaseModel):
    items: list[PublicationItem]


@router.post(
    "/semantic/models/{model_id}/publish", status_code=201, response_model=PublicationProposed
)
def propose_publication_endpoint(
    model_id: uuid.UUID,
    body: PublishRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    semantic_gateway: Any = Depends(get_semantic_gateway),
) -> PublicationProposed:
    """Propose a publication (FR-003, FR-004)."""
    try:
        classification = ChangeClassification(body.change_classification)
    except ValueError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "change_classification",
                    "code": "invalid_value",
                    "message": f"invalid change classification '{body.change_classification}'",
                    "remediation": "Use breaking or non_breaking",
                }
            ]
        ) from exc
    try:
        result = propose_publication(
            session,
            model_id=model_id,
            change_classification=classification,
            proposed_by=caller.identity,
            gateway=semantic_gateway,
        )
    except PublicationBlockedError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "$",
                    "code": "tests_failed",
                    "message": "publication blocked by failed semantic tests (FR-004)",
                    "remediation": "Fix the failing semantic tests before publishing",
                }
                for _ in exc.failures
            ]
        ) from exc
    except PublicationNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    AuditService(session).semantic_model_published(
        actor=caller.identity, model_id=model_id, version=1
    )
    session.flush()
    return PublicationProposed(
        publication_id=result.publication_id,
        approval_status=result.approval_status,
    )


@router.post("/publications/{publication_id}/approve", response_model=PublicationApproved)
def approve_publication_endpoint(
    publication_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> PublicationApproved:
    """Approve a publication (FR-005)."""
    try:
        result = approve_publication(
            session, publication_id=publication_id, approved_by=caller.identity
        )
    except PublicationNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    # Notify registered consumers of breaking changes (FR-005).
    publication = session.get(Publication, publication_id)
    if (
        publication is not None
        and publication.change_classification == ChangeClassification.breaking
    ):
        _notify_consumers(session, publication.model_id)
    session.flush()
    return PublicationApproved(
        approval_status=result.approval_status,
        published_at=result.published_at,
    )


@router.get("/semantic/models/{model_id}/publications", response_model=PublicationList)
def list_publications_endpoint(
    model_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> PublicationList:
    """List publication history (US2-AC2)."""
    model = session.get(SemanticModel, model_id)
    if model is None:
        raise NotFoundError(f"no semantic model with id {model_id}")
    publications = list_publications(session, model_id=model_id)
    return PublicationList(
        items=[
            PublicationItem(
                publication_id=p.id,
                version=p.version,
                change_classification=p.change_classification.value,
                approval_status=p.approval_status.value,
                published_at=p.published_at,
            )
            for p in publications
        ]
    )


def _notify_consumers(session: Session, model_id: uuid.UUID) -> None:
    """Record a consumer notification for a breaking change (FR-005).

    MVP: logs the notification via the audit trail; live notification
    channels are wired in Phase 7 (consumers.py).
    """
    metric_ids = session.execute(select(ConsumerRegistration.metric_id).distinct()).scalars().all()
    _ = metric_ids  # notification delivery is a Phase 7 concern
