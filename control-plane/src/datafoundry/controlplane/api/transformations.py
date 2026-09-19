"""API router: transformations (T026, contracts/processing-api.md §2).

- ``POST /transformations`` — define a transformation (FR-005): validate (all
  errors at once) -> persist -> audit ``transformation.defined`` -> 201. 422
  on invalid source/target layer / bad logic / secret-scan hit.
- ``GET /transformations/{id}`` — export a transformation (FR-005):
  logic_definition + logic_hash.
- ``POST /transformations/{id}/run`` — run the transformation (FR-005,
  FR-017): transform -> gate -> promote/block; returns output_version,
  record_count, quarantined_count, gate_report_id, promotion_state.
- ``GET /transformations/{id}/runs`` — run history (FR-017).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import (
    get_db,
    get_processing_gateway,
    get_quality_gateway,
)
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.transformation_schema import (
    TransformationConfigError,
    gitops_provenance,
    validate_transformation_definition,
)
from datafoundry.controlplane.db.models import (
    ConfigSource,
    DatasetLayer,
    DatasetVersion,
    PromotionStateRow,
    Transformation,
)
from datafoundry.controlplane.processing.engine import run_transformation
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["transformations"])


# -- response models ------------------------------------------------------------


class TransformationDefined(BaseModel):
    transformation_id: uuid.UUID
    version: int


class TransformationExport(BaseModel):
    transformation_id: uuid.UUID
    version: int
    logic_definition: dict[str, Any]
    logic_hash: str


class RunRequest(BaseModel):
    input_dataset_id: uuid.UUID
    environment: str = "production"


class RunResponse(BaseModel):
    output_dataset_id: uuid.UUID
    output_version: int
    record_count: int
    quarantined_count: int
    gate_report_id: str | None
    promotion_state: str


class RunItem(BaseModel):
    run_id: uuid.UUID
    input_version: int | None
    output_version: int
    record_count: int
    quarantined_count: int
    gate_report_id: str | None
    promotion_state: str | None
    ran_at: str


class RunList(BaseModel):
    items: list[RunItem]


# -- helpers ---------------------------------------------------------------------


def _get_transformation(session: Session, transformation_id: uuid.UUID) -> Transformation:
    transformation = session.get(Transformation, transformation_id)
    if transformation is None:
        raise NotFoundError(f"no transformation with id {transformation_id}")
    return transformation


def _logic_hash(logic_definition: dict[str, Any]) -> str:
    canonical = json.dumps(logic_definition, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _error_path(msg: str) -> str:
    return msg.split(":", 1)[0] if ":" in msg else "$"


# -- routes ----------------------------------------------------------------------


@router.post("/transformations", status_code=201, response_model=TransformationDefined)
def define_transformation(
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> TransformationDefined:
    """Define a transformation (FR-005)."""
    try:
        definition = validate_transformation_definition(body)
    except TransformationConfigError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": _error_path(msg),
                    "code": "invalid_value",
                    "message": msg,
                    "remediation": (
                        "Correct the transformation per contracts/transformation-schema.md"
                    ),
                }
                for msg in exc.errors
            ]
        ) from exc

    # Version per name: each accepted definition increments version.
    latest = session.execute(
        select(Transformation.version)
        .where(Transformation.name == definition.name)
        .order_by(Transformation.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    version = (latest or 0) + 1

    logic_hash = _logic_hash(definition.logic.model_dump())
    provenance = gitops_provenance(definition.git_ref)
    transformation = Transformation(
        name=definition.name,
        version=version,
        source_layer=DatasetLayer(definition.source_layer),
        target_layer=DatasetLayer(definition.target_layer),
        logic_definition=definition.logic.model_dump(),
        logic_hash=logic_hash,
        dedup_keys=definition.dedup_keys,
        reconciliation_tolerance=definition.reconciliation_tolerance,
        owner_identity=caller.identity,
        source=ConfigSource(provenance["source"]),
        git_ref=definition.git_ref,
    )
    session.add(transformation)
    session.flush()

    AuditService(session).transformation_defined(
        actor=caller.identity,
        platform_id=None,
        transformation_id=transformation.id,
        name=transformation.name,
        version=transformation.version,
        logic_hash=transformation.logic_hash,
    )
    session.flush()
    return TransformationDefined(
        transformation_id=transformation.id, version=transformation.version
    )


@router.get("/transformations/{transformation_id}", response_model=TransformationExport)
def get_transformation(
    transformation_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> TransformationExport:
    """Export a transformation (FR-005)."""
    transformation = _get_transformation(session, transformation_id)
    return TransformationExport(
        transformation_id=transformation.id,
        version=transformation.version,
        logic_definition=dict(transformation.logic_definition or {}),
        logic_hash=transformation.logic_hash,
    )


@router.post(
    "/transformations/{transformation_id}/run",
    response_model=RunResponse,
)
def run_transformation_endpoint(
    transformation_id: uuid.UUID,
    body: RunRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    processing_gateway: Any = Depends(get_processing_gateway),
    quality_gateway: Any = Depends(get_quality_gateway),
) -> RunResponse:
    """Run the transformation (FR-005, FR-017)."""
    transformation = _get_transformation(session, transformation_id)
    result = run_transformation(
        session,
        gateway=processing_gateway,
        transformation_id=transformation.id,
        dataset_id=body.input_dataset_id,
        environment=body.environment,
        quality_gateway=quality_gateway,
    )
    AuditService(session).transformation_run(
        actor=caller.identity,
        platform_id=None,
        transformation_id=transformation.id,
        dataset_id=uuid.UUID(result["output_dataset_id"]),
        output_version=result["output_version"],
    )
    session.flush()
    return RunResponse(**result)


@router.get("/transformations/{transformation_id}/runs", response_model=RunList)
def list_transformation_runs(
    transformation_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> RunList:
    """Run history for a transformation (FR-017)."""
    transformation = _get_transformation(session, transformation_id)
    versions = session.execute(
        select(DatasetVersion)
        .where(DatasetVersion.transformation_id == transformation.id)
        .order_by(DatasetVersion.version.desc())
    ).scalars()
    items = []
    for version in versions:
        promo = session.execute(
            select(PromotionStateRow).where(PromotionStateRow.dataset_id == version.dataset_id)
        ).scalar_one_or_none()
        input_version = None
        if version.input_versions:
            input_version = next(iter(version.input_versions.values()), None)
        items.append(
            RunItem(
                run_id=version.id,
                input_version=input_version,
                output_version=version.version,
                record_count=version.record_count,
                quarantined_count=version.quarantined_count,
                gate_report_id=(str(version.gate_report_id) if version.gate_report_id else None),
                promotion_state=promo.state.value if promo else None,
                ran_at=version.created_at.isoformat(),
            )
        )
    return RunList(items=items)
