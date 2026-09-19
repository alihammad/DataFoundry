"""API router: protection policies (T021, contracts/security-api.md §2).

- ``POST /policies`` — define a protection policy (FR-002): 201 policy_id;
  422 invalid mechanism / missing key_ref for encrypt/tokenise / secret-scan.
- ``GET /policies`` — list policies.
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import ConfigValidationError
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.security_schema import (
    SecurityConfigError,
    validate_protection_policy,
)
from datafoundry.controlplane.db.models import (
    KeyReference,
    ProtectionMechanism,
    ProtectionPolicy,
    SecurityLevel,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["protection"])


class PolicyDefined(BaseModel):
    policy_id: uuid.UUID


class PolicyItem(BaseModel):
    policy_id: uuid.UUID
    name: str
    classification: str
    mechanism: str
    authorised_roles: list[str]


class PolicyList(BaseModel):
    items: list[PolicyItem]


def _error_path(msg: str) -> str:
    return msg.split(":", 1)[0] if ":" in msg else "$"


@router.post("/policies", status_code=201, response_model=PolicyDefined)
def define_policy(
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> PolicyDefined:
    """Define a protection policy (FR-002)."""
    try:
        definition = validate_protection_policy(body)
    except SecurityConfigError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": _error_path(msg),
                    "code": "invalid_value",
                    "message": msg,
                    "remediation": "Correct the policy per contracts/protection-policy-schema.md",
                }
                for msg in exc.errors
            ]
        ) from exc

    key_ref_id = uuid.UUID(definition.key_ref_id) if definition.key_ref_id else None
    if key_ref_id is not None and session.get(KeyReference, key_ref_id) is None:
        raise ConfigValidationError(
            [
                {
                    "path": "key_ref_id",
                    "code": "unknown_key",
                    "message": f"no key reference with id {key_ref_id}",
                    "remediation": "Register the key first (POST /keys)",
                }
            ]
        )

    policy = ProtectionPolicy(
        name=definition.name,
        classification=SecurityLevel(definition.classification),
        mechanism=ProtectionMechanism(definition.mechanism),
        key_ref_id=key_ref_id,
        token_service_ref=definition.token_service_ref,
        authorised_roles=definition.authorised_roles,
        detokenise_roles=definition.detokenise_roles,
        masking_rule=definition.masking_rule,
        created_by=caller.identity,
    )
    session.add(policy)
    session.flush()
    AuditService(session).security_policy_change(
        actor=caller.identity, policy_id=policy.id, name=policy.name
    )
    session.flush()
    return PolicyDefined(policy_id=policy.id)


@router.get("/policies", response_model=PolicyList)
def list_policies(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> PolicyList:
    """List protection policies."""
    policies = session.execute(
        select(ProtectionPolicy).order_by(ProtectionPolicy.created_at)
    ).scalars()
    return PolicyList(
        items=[
            PolicyItem(
                policy_id=p.id,
                name=p.name,
                classification=p.classification.value,
                mechanism=p.mechanism.value,
                authorised_roles=list(p.authorised_roles or []),
            )
            for p in policies
        ]
    )
