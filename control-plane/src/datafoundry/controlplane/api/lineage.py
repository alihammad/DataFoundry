"""API router: lineage (T043, contracts/processing-api.md §4).

- ``GET /datasets/{id}/lineage`` — upstream + downstream lineage for a dataset
  (FR-015, SC-006), navigable in both directions.
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import NotFoundError
from datafoundry.controlplane.db.models import Dataset
from datafoundry.controlplane.processing.lineage import get_lineage
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["lineage"])


class LineageNode(BaseModel):
    dataset_id: uuid.UUID
    layer: str
    transformation_id: str | None
    transformation_version: int | None


class LineageResponse(BaseModel):
    upstream: list[LineageNode]
    downstream: list[LineageNode]


@router.get("/datasets/{dataset_id}/lineage", response_model=LineageResponse)
def dataset_lineage(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> LineageResponse:
    """Lineage for a dataset, navigable both directions (FR-015)."""
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    lineage = get_lineage(session, dataset_id=dataset_id)
    return LineageResponse(
        upstream=[LineageNode(**node) for node in lineage["upstream"]],
        downstream=[LineageNode(**node) for node in lineage["downstream"]],
    )
