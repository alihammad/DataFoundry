"""API router: access enforcement (T038, contracts/security-api.md §5).

- ``POST /access/decide`` — evaluate the enforcement chain for a request
  (FR-013): 200 outcome granted/denied with classification_consulted /
  policy_applied / reason. Evaluated at query time — no cached grants.
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import ConfigValidationError
from datafoundry.controlplane.security.access import decide_access
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

router = APIRouter(tags=["access"])


class AccessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity: str
    resource: str
    action: str


class AccessResponse(BaseModel):
    outcome: str
    classification_consulted: str
    policy_applied: str | None
    reason: str | None


def _parse_resource(resource: str) -> tuple[uuid.UUID, str | None]:
    """Parse ``dataset:<uuid>:column:<name>`` into (dataset_id, column).

    The column segment is optional (dataset-level resource).
    """
    parts = resource.split(":")
    if len(parts) < 2 or parts[0] != "dataset":
        raise ConfigValidationError(
            [
                {
                    "path": "resource",
                    "code": "invalid_value",
                    "message": f"invalid resource '{resource}'",
                    "remediation": "Use 'dataset:<uuid>:column:<name>'",
                }
            ]
        )
    try:
        dataset_id = uuid.UUID(parts[1])
    except ValueError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "resource",
                    "code": "invalid_value",
                    "message": f"invalid dataset id in resource '{resource}'",
                    "remediation": "Use a valid dataset uuid",
                }
            ]
        ) from exc
    column = None
    if len(parts) >= 4 and parts[2] == "column":
        column = parts[3]
    return dataset_id, column


def _roles_for_identity(identity: str, caller: Caller) -> list[str]:
    """Resolve RBAC roles for an identity (FR-013).

    MVP: the dev caller's roles apply to the dev identity; otherwise roles are
    derived from the identity's local-part (e.g. ``analyst@acme.com`` ->
    ``analyst``, ``security-officer@acme.com`` -> ``security-officer``). This
    mirrors the quickstart Scenario 5 role model.
    """
    if identity == caller.identity:
        return list(caller.roles)
    local = identity.split("@", 1)[0]
    return [local] if local else []


@router.post("/access/decide", response_model=AccessResponse)
def decide_access_endpoint(
    body: AccessRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> AccessResponse:
    """Evaluate the enforcement chain at query time (FR-013)."""
    dataset_id, column = _parse_resource(body.resource)
    roles = _roles_for_identity(body.identity, caller)
    result = decide_access(
        session,
        identity=body.identity,
        resource=body.resource,
        action=body.action,
        roles=roles,
        dataset_id=dataset_id,
        column=column,
    )
    session.flush()
    return AccessResponse(
        outcome=result.outcome,
        classification_consulted=result.classification_consulted,
        policy_applied=result.policy_applied,
        reason=result.reason,
    )
