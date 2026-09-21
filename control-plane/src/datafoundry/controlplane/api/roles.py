"""UI-role API router (feature 007, T019/T043, ui-api.md §4).

- ``POST /ui/roles`` — create a role (FR-013/FR-014): 201; 422 invalid scope.
- ``GET /ui/roles`` — list roles.
- ``POST /ui/roles/{role_id}/assign`` — assign a user to a role (admin only).
- ``GET /ui/roles/{role_id}/assignments`` — list assignments.
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
from datafoundry.controlplane.config.ui_schema import UIRoleAssign, UIRoleCreate
from datafoundry.controlplane.db.models import UIRole, UIRoleAssignment
from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/ui/roles", tags=["ui-roles"])

#: MVP admin identity — the dev identity is the platform administrator.
ADMIN_IDENTITY = "dev@datafoundry.local"


def _require_admin(caller: Caller) -> None:
    if caller.identity != ADMIN_IDENTITY:
        raise ForbiddenError(["ui.admin"])


@router.post("", status_code=201)
def create_role(
    body: UIRoleCreate,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    _require_admin(caller)
    try:
        body = UIRoleCreate.model_validate(body.model_dump())
    except ValidationError as exc:
        errors = [
            {"path": ".".join(str(p) for p in e["loc"]), "code": e["type"], "message": e["msg"]}
            for e in exc.errors()
        ]
        raise ConfigValidationError(errors) from exc

    existing = session.execute(select(UIRole).where(UIRole.name == body.name)).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("name_taken", "role name already exists")
    role = UIRole(
        name=body.name,
        scope=body.scope,
        permissions=body.permissions,
        platform_scope=body.platform_scope,
        dataset_scope=[d.model_dump() for d in body.dataset_scope],
        created_by=caller.identity,
    )
    session.add(role)
    session.flush()
    AuditService(session).ui_role_created(
        actor=caller.identity, role_id=role.id, name=role.name, scope=str(role.scope)
    )
    return {"role_id": str(role.id)}


@router.get("")
def list_roles(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, list[dict]]:
    rows = session.execute(select(UIRole)).scalars()
    return {
        "items": [
            {
                "role_id": str(r.id),
                "name": r.name,
                "scope": str(r.scope),
                "permissions": r.permissions,
            }
            for r in rows
        ]
    }


@router.post("/{role_id}/assign", status_code=201)
def assign_role(
    role_id: uuid.UUID,
    body: UIRoleAssign,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, str]:
    _require_admin(caller)
    role = session.get(UIRole, role_id)
    if role is None:
        raise NotFoundError("role not found")
    existing = session.execute(
        select(UIRoleAssignment).where(
            UIRoleAssignment.role_id == role_id,
            UIRoleAssignment.user_identity == body.user_identity,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("already_assigned", "user already assigned to role")
    assignment = UIRoleAssignment(
        role_id=role_id,
        user_identity=body.user_identity,
        granted_by=caller.identity,
    )
    session.add(assignment)
    session.flush()
    AuditService(session).ui_role_assigned(
        actor=caller.identity,
        role_id=role_id,
        assignment_id=assignment.id,
        user_identity=body.user_identity,
    )
    return {"assignment_id": str(assignment.id)}


@router.get("/{role_id}/assignments")
def list_assignments(
    role_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> dict[str, list[dict]]:
    rows = session.execute(
        select(UIRoleAssignment).where(UIRoleAssignment.role_id == role_id)
    ).scalars()
    return {
        "items": [
            {
                "assignment_id": str(a.id),
                "user_identity": a.user_identity,
                "granted_at": a.granted_at.isoformat(),
            }
            for a in rows
        ]
    }
