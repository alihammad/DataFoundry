"""API router: datasets (T019, contracts/processing-api.md §1).

- ``POST /datasets`` — register a dataset (FR-014): validate (all errors at
  once) -> persist Dataset -> audit ``dataset.registered`` -> 201. 422 on
  unknown layer / bad name / missing owner / secret-scan hit; 409 on
  duplicate (platform_id, name).
- ``GET /datasets`` — list datasets visible to the caller.
- ``GET /datasets/{id}`` — dataset detail with current promotion state, gate
  results, and last transition timestamp (US4-AC3).
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ConflictError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.dataset_schema import (
    DatasetConfigError,
    validate_dataset_definition,
)
from datafoundry.controlplane.db.models import (
    DataClassification,
    Dataset,
    DatasetLayer,
    Platform,
    PromotionStateRow,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["datasets"])


# -- response models ------------------------------------------------------------


class DatasetRegistered(BaseModel):
    dataset_id: uuid.UUID


class DatasetItem(BaseModel):
    dataset_id: uuid.UUID
    name: str
    layer: str
    owner: str
    classification: str
    promotion_state: str | None
    quality_score: float | None


class DatasetList(BaseModel):
    items: list[DatasetItem]


class DatasetDetail(BaseModel):
    dataset_id: uuid.UUID
    name: str
    layer: str
    owner: str
    steward: str | None
    domain: str | None
    description: str | None
    classification: str
    quality_score: float | None
    refresh_metadata: dict[str, Any] | None
    schema_definition: dict[str, Any]
    promotion_state: str | None
    gate_report_id: str | None
    transitioned_at: str | None
    blocked_reason: str | None


# -- helpers ---------------------------------------------------------------------


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


def _promotion(session: Session, dataset_id: uuid.UUID) -> PromotionStateRow | None:
    return session.execute(
        select(PromotionStateRow).where(PromotionStateRow.dataset_id == dataset_id)
    ).scalar_one_or_none()


def _error_path(msg: str) -> str:
    return msg.split(":", 1)[0] if ":" in msg else "$"


# -- routes ----------------------------------------------------------------------


@router.post("/datasets", status_code=201, response_model=DatasetRegistered)
def register_dataset(
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> DatasetRegistered:
    """Register a dataset (FR-014)."""
    try:
        definition = validate_dataset_definition(body)
    except DatasetConfigError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": _error_path(msg),
                    "code": "invalid_value",
                    "message": msg,
                    "remediation": (
                        "Correct the dataset registration per contracts/dataset-schema.md"
                    ),
                }
                for msg in exc.errors
            ]
        ) from exc

    platform = session.get(Platform, uuid.UUID(definition.platform_id))
    if platform is None:
        raise NotFoundError(f"no platform with id {definition.platform_id}")

    existing = session.execute(
        select(Dataset).where(
            Dataset.platform_id == platform.id,
            Dataset.name == definition.name,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("name_taken", f"dataset name '{definition.name}' already registered")

    dataset = Dataset(
        platform_id=platform.id,
        name=definition.name,
        layer=DatasetLayer(definition.layer),
        schema_definition=definition.schema_definition,
        owner_identity=definition.owner_identity,
        steward_identity=definition.steward_identity,
        domain=definition.domain,
        description=definition.description,
        classification=DataClassification(definition.classification),
        refresh_metadata=definition.refresh_metadata,
        quality_score=definition.quality_score,
    )
    session.add(dataset)
    session.flush()

    AuditService(session).dataset_registered(
        actor=caller.identity,
        platform_id=platform.id,
        dataset_id=dataset.id,
        name=dataset.name,
        layer=dataset.layer.value,
    )
    session.flush()
    return DatasetRegistered(dataset_id=dataset.id)


@router.get("/datasets", response_model=DatasetList)
def list_datasets(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> DatasetList:
    """List datasets visible to the caller."""
    datasets = session.execute(select(Dataset).order_by(Dataset.created_at)).scalars()
    items = []
    for dataset in datasets:
        promo = _promotion(session, dataset.id)
        items.append(
            DatasetItem(
                dataset_id=dataset.id,
                name=dataset.name,
                layer=dataset.layer.value,
                owner=dataset.owner_identity,
                classification=dataset.classification.value,
                promotion_state=promo.state.value if promo else None,
                quality_score=dataset.quality_score,
            )
        )
    return DatasetList(items=items)


@router.get("/datasets/{dataset_id}", response_model=DatasetDetail)
def get_dataset(
    dataset_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> DatasetDetail:
    """Dataset detail with promotion state + gate results (US4-AC3)."""
    dataset = _get_dataset(session, dataset_id)
    promo = _promotion(session, dataset.id)
    return DatasetDetail(
        dataset_id=dataset.id,
        name=dataset.name,
        layer=dataset.layer.value,
        owner=dataset.owner_identity,
        steward=dataset.steward_identity,
        domain=dataset.domain,
        description=dataset.description,
        classification=dataset.classification.value,
        quality_score=dataset.quality_score,
        refresh_metadata=dict(dataset.refresh_metadata or {}),
        schema_definition=dict(dataset.schema_definition or {}),
        promotion_state=promo.state.value if promo else None,
        gate_report_id=str(promo.gate_report_id) if promo and promo.gate_report_id else None,
        transitioned_at=(
            promo.transitioned_at.isoformat() if promo and promo.transitioned_at else None
        ),
        blocked_reason=promo.blocked_reason if promo else None,
    )
