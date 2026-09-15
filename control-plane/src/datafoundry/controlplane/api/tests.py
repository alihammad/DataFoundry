"""API router: tests listing helper (T019, contracts/quality-api.md §2).

``GET /datasets/{dataset_id}/tests`` — list configured tests for a dataset
across all its gates (read-only).
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import NotFoundError
from datafoundry.controlplane.db.models import Dataset, QualityGate, QualityTest
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["tests"])


class TestItem(BaseModel):
    test_id: uuid.UUID
    name: str
    category: str
    severity: str
    parameters: dict[str, Any]


class TestsListResponse(BaseModel):
    items: list[TestItem]


@router.get("/datasets/{dataset_id}/tests", response_model=TestsListResponse)
def list_tests(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> TestsListResponse:
    """List configured tests for a dataset (read-only, FR-015)."""
    if session.get(Dataset, dataset_id) is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")

    gate_ids = session.execute(
        select(QualityGate.id).where(QualityGate.dataset_id == dataset_id)
    ).scalars()
    tests = session.execute(
        select(QualityTest).where(QualityTest.gate_id.in_(list(gate_ids)))
    ).scalars()
    return TestsListResponse(
        items=[
            TestItem(
                test_id=t.id,
                name=t.name,
                category=t.category.value,
                severity=t.severity.value,
                parameters=t.parameters or {},
            )
            for t in tests
        ]
    )
