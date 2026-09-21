"""API router: semantic discovery (T036, contracts/semantic-api.md §6).

- ``GET /semantic/discovery?q=...`` — search business terms (FR-011, US4):
  200 with certified metrics + metadata; drafts hidden from general users or
  clearly marked (US4-AC2).
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.semantic.discovery import search_business_terms
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["semantic"])


class DiscoveryItemOut(BaseModel):
    metric_id: uuid.UUID
    name: str
    business_definition: str
    owner_identity: str
    quality_score: float | None
    freshness: str | None
    lineage: dict[str, Any]
    certification_state: str
    consuming_teams: list[str]


class DiscoveryResponse(BaseModel):
    items: list[DiscoveryItemOut]


@router.get("/semantic/discovery", response_model=DiscoveryResponse)
def discovery(
    q: str = "",
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> DiscoveryResponse:
    """Search business terms (FR-011, US4)."""
    items = search_business_terms(session, query=q)
    return DiscoveryResponse(
        items=[
            DiscoveryItemOut(
                metric_id=item.metric_id,
                name=item.name,
                business_definition=item.business_definition,
                owner_identity=item.owner_identity,
                quality_score=item.quality_score,
                freshness=item.freshness,
                lineage=item.lineage,
                certification_state=item.certification_state,
                consuming_teams=item.consuming_teams,
            )
            for item in items
        ]
    )
