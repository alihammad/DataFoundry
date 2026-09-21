"""Saved-query API router (feature 007, T019/T036, ui-api.md §2).

- ``POST /ui/saved-queries`` — save a query (FR-010): 201; 422 invalid/secret-scan.
- ``GET /ui/saved-queries`` — list my saved queries.
- ``GET /ui/saved-queries/{query_id}`` — get a saved query (owner or shared).
- ``POST /ui/saved-queries/{query_id}/share`` — share a query (owner only).
- ``POST /ui/saved-queries/{query_id}/run`` — run a saved query (re-evaluates
  the runner's access rights; MVP returns the stored SQL for the client to run
  through the existing query API).
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.ui_schema import (
    SavedQueryCreate,
    SavedQueryShareCreate,
)
from datafoundry.controlplane.db.models import SavedQuery, SavedQueryShare
from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ui/saved-queries", tags=["ui-saved-queries"])


def _not_found() -> NotFoundError:
    return NotFoundError("saved query not found")


@router.post("", status_code=201)
def create_saved_query(
    body: SavedQueryCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    try:
        body = SavedQueryCreate.model_validate(body.model_dump())
    except ValidationError as exc:
        errors = [
            {"path": ".".join(str(p) for p in e["loc"]), "code": e["type"], "message": e["msg"]}
            for e in exc.errors()
        ]
        raise ConfigValidationError(errors) from exc

    query = SavedQuery(
        name=body.name,
        owner_identity=caller.identity,
        sql_text=body.sql_text,
        dataset_bindings=body.dataset_bindings,
        sharing=body.sharing,
    )
    session.add(query)
    session.flush()
    AuditService(session).ui_saved_query_created(
        actor=caller.identity, query_id=query.id, name=query.name, sharing=str(query.sharing)
    )
    return {"query_id": str(query.id)}


@router.get("")
def list_saved_queries(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, list[dict]]:
    rows = session.execute(
        select(SavedQuery).where(SavedQuery.owner_identity == caller.identity)
    ).scalars()
    return {
        "items": [
            {
                "query_id": str(q.id),
                "name": q.name,
                "owner_identity": q.owner_identity,
                "sharing": str(q.sharing),
                "created_at": q.created_at.isoformat(),
            }
            for q in rows
        ]
    }


@router.get("/{query_id}")
def get_saved_query(
    query_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict:
    query = session.get(SavedQuery, query_id)
    if query is None:
        raise _not_found()
    if query.owner_identity != caller.identity:
        shared = session.execute(
            select(SavedQueryShare).where(
                SavedQueryShare.query_id == query_id,
                SavedQueryShare.shared_with_identity == caller.identity,
            )
        ).scalar_one_or_none()
        if shared is None:
            raise ForbiddenError(["saved_query.read"])
    return {
        "query_id": str(query.id),
        "name": query.name,
        "sql_text": query.sql_text,
        "dataset_bindings": query.dataset_bindings,
        "sharing": str(query.sharing),
        "owner_identity": query.owner_identity,
        "created_at": query.created_at.isoformat(),
    }


@router.post("/{query_id}/share", status_code=201)
def share_saved_query(
    query_id: uuid.UUID,
    body: SavedQueryShareCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    query = session.get(SavedQuery, query_id)
    if query is None:
        raise _not_found()
    if query.owner_identity != caller.identity:
        raise ForbiddenError(["saved_query.share"])
    existing = session.execute(
        select(SavedQueryShare).where(
            SavedQueryShare.query_id == query_id,
            SavedQueryShare.shared_with_identity == body.shared_with_identity,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("already_shared", "already shared with that user")
    share = SavedQueryShare(
        query_id=query_id,
        shared_with_identity=body.shared_with_identity,
        shared_by=caller.identity,
    )
    session.add(share)
    session.flush()
    AuditService(session).ui_saved_query_shared(
        actor=caller.identity, query_id=query_id, shared_with_identity=body.shared_with_identity
    )
    return {"share_id": str(share.id)}


@router.post("/{query_id}/run")
def run_saved_query(
    query_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict:
    query = session.get(SavedQuery, query_id)
    if query is None:
        raise _not_found()
    if query.owner_identity != caller.identity:
        shared = session.execute(
            select(SavedQueryShare).where(
                SavedQueryShare.query_id == query_id,
                SavedQueryShare.shared_with_identity == caller.identity,
            )
        ).scalar_one_or_none()
        if shared is None:
            raise ForbiddenError(["saved_query.run"])
    # MVP: return the stored SQL + bindings; the client runs it through the
    # existing query API, which re-evaluates the runner's access rights.
    return {
        "query_id": str(query.id),
        "sql_text": query.sql_text,
        "dataset_bindings": query.dataset_bindings,
    }
