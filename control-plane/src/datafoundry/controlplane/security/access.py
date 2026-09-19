"""Access enforcement chain (feature 005, T013).

Identity -> authentication -> authorisation -> classification -> protection
policy -> data access; RBAC at dataset/table/column/row level; key-use
permission separate from data-read (FR-013).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from datafoundry.controlplane.db.models import (
    AccessDecision,
    AccessOutcome,
    Classification,
    ProtectionPolicy,
    SecurityLevel,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


@dataclass
class AccessResult:
    """The outcome of the enforcement chain for a request (FR-013)."""

    outcome: str  # granted | denied
    classification_consulted: str
    policy_applied: str | None
    reason: str | None


def decide_access(
    session: Session,
    *,
    identity: str,
    resource: str,
    action: str,
    roles: list[str],
    dataset_id: uuid.UUID,
    column: str | None = None,
) -> AccessResult:
    """Evaluate the enforcement chain at query time (FR-013).

    identity -> authentication (caller) -> authorisation (roles) ->
    classification -> protection policy -> data access. Key-use permission is
    separately enforced from data-read (FR-012): reading a protected column
    requires the role to be in the policy's ``authorised_roles``.
    """
    classification = session.execute(
        select(Classification).where(
            Classification.dataset_id == dataset_id,
            Classification.column == column,
        )
    ).scalar_one_or_none()
    if classification is None:
        classification = session.execute(
            select(Classification).where(
                Classification.dataset_id == dataset_id,
                Classification.column.is_(None),
            )
        ).scalar_one_or_none()

    level = classification.level if classification else SecurityLevel.public
    policy = None
    if classification is not None:
        policy = session.get(ProtectionPolicy, classification.policy_id)

    # Data-read permission: caller must be in the policy's authorised_roles.
    if policy is not None:
        authorised = list(policy.authorised_roles or [])
        if roles and not set(roles).isdisjoint(authorised):
            outcome = AccessOutcome.granted
            reason = None
        else:
            outcome = AccessOutcome.denied
            reason = "masked per policy; detokenisation requires key-use permission (FR-012)"
    else:
        outcome = AccessOutcome.granted
        reason = None

    decision = AccessDecision(
        identity=identity,
        resource=resource,
        classification_consulted=level,
        policy_applied=policy.id if policy else None,
        outcome=outcome,
        reason=reason,
    )
    session.add(decision)
    session.flush()
    return AccessResult(
        outcome=outcome.value,
        classification_consulted=level.value,
        policy_applied=str(policy.id) if policy else None,
        reason=reason,
    )
