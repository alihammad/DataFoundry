"""API router: semantic models (T019, contracts/semantic-api.md §1).

- ``POST /semantic/models`` — define a semantic model (FR-001/FR-003): 201
  model_id/version/certification_state; 422 all errors at once.
- ``GET /semantic/models/{id}`` — export a semantic model (FR-003).
- ``GET /semantic/models`` — list semantic models.
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import ConfigValidationError, NotFoundError
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.semantic_schema import SemanticConfigError
from datafoundry.controlplane.db.models import SemanticModel
from datafoundry.controlplane.semantic.model.model import (
    SemanticModelError,
    compose_semantic_model,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["semantic"])


class ModelDefined(BaseModel):
    model_id: uuid.UUID
    version: int
    certification_state: str


class ModelItem(BaseModel):
    model_id: uuid.UUID
    domain: str
    version: int
    certification_state: str


class ModelList(BaseModel):
    items: list[ModelItem]


class ModelDetail(BaseModel):
    model_id: uuid.UUID
    domain: str
    version: int
    certification_state: str
    config_yaml: str
    config_hash: str


def _get_model(session: Session, model_id: uuid.UUID) -> SemanticModel:
    model = session.get(SemanticModel, model_id)
    if model is None:
        raise NotFoundError(f"no semantic model with id {model_id}")
    return model


@router.post("/semantic/models", status_code=201, response_model=ModelDefined)
def define_semantic_model(
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ModelDefined:
    """Define a semantic model (FR-001, FR-003)."""
    try:
        composed = compose_semantic_model(
            session,
            config=body,
            created_by=caller.identity,
        )
    except SemanticConfigError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": _error_path(msg),
                    "code": "invalid_value",
                    "message": msg,
                    "remediation": (
                        "Correct the semantic model per contracts/semantic-model-schema.md"
                    ),
                }
                for msg in exc.errors
            ]
        ) from exc
    except SemanticModelError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "$",
                    "code": "invalid_value",
                    "message": str(exc),
                    "remediation": "Resolve the referenced datasets",
                }
            ]
        ) from exc
    AuditService(session).semantic_model_defined(
        actor=caller.identity,
        model_id=composed.model.id,
        domain=composed.model.domain,
        version=composed.model.version,
    )
    session.flush()
    return ModelDefined(
        model_id=composed.model.id,
        version=composed.model.version,
        certification_state=composed.model.certification_state.value,
    )


@router.get("/semantic/models/{model_id}", response_model=ModelDetail)
def get_semantic_model(
    model_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ModelDetail:
    """Export a semantic model (FR-003)."""
    model = _get_model(session, model_id)
    return ModelDetail(
        model_id=model.id,
        domain=model.domain,
        version=model.version,
        certification_state=model.certification_state.value,
        config_yaml=model.config_yaml,
        config_hash=model.config_hash,
    )


@router.get("/semantic/models", response_model=ModelList)
def list_semantic_models(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ModelList:
    """List semantic models."""
    models = session.execute(select(SemanticModel).order_by(SemanticModel.created_at)).scalars()
    return ModelList(
        items=[
            ModelItem(
                model_id=m.id,
                domain=m.domain,
                version=m.version,
                certification_state=m.certification_state.value,
            )
            for m in models
        ]
    )


def _error_path(msg: str) -> str:
    return msg.split(":", 1)[0] if ":" in msg else "$"
