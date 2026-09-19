"""Protection policy resolution (feature 005, T009).

Maps a classification to an enforceable policy; mechanism per column is
policy-driven, never ad hoc (FR-002).
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.db.models import ProtectionPolicy, SecurityLevel
from sqlalchemy import select
from sqlalchemy.orm import Session


class PolicyNotFoundError(KeyError):
    """Raised when a protection policy id does not exist."""


def get_policy(session: Session, *, policy_id: uuid.UUID) -> ProtectionPolicy:
    """Fetch a protection policy by id."""
    policy = session.get(ProtectionPolicy, policy_id)
    if policy is None:
        raise PolicyNotFoundError(f"no protection policy with id {policy_id}")
    return policy


def resolve_policy_for_classification(
    session: Session, *, classification: SecurityLevel
) -> ProtectionPolicy | None:
    """Resolve the enforceable policy for a classification (FR-002).

    Returns the most recently created policy matching the classification, or
    None when none is defined.
    """
    return session.execute(
        select(ProtectionPolicy)
        .where(ProtectionPolicy.classification == classification)
        .order_by(ProtectionPolicy.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
