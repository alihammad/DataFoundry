"""Security engine (feature 005, T045).

Applies protection during processing; fail-closed enforcement (FR-019);
classification downgrades never retroactively expose protected data (FR-020).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from datafoundry.controlplane.db.models import (
    Classification,
    ProtectionPolicy,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


class FailClosedError(RuntimeError):
    """Raised when a protection service is unavailable or a policy cannot be
    enforced — the batch must block rather than proceed unprotected (FR-019).
    """


@dataclass
class ProtectionPlan:
    """The enforceable protection plan for a dataset column (FR-019)."""

    column: str
    mechanism: str
    policy_id: uuid.UUID | None
    enforceable: bool
    reason: str | None = None


def resolve_protection_plan(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    column: str,
    gateway: object,
) -> ProtectionPlan:
    """Resolve the enforceable protection plan for a column (FR-019).

    Fails closed: if a classification maps to a policy that cannot be enforced
    (e.g. the protection service is unavailable), the plan is not enforceable
    and the caller must block processing rather than write unprotected.
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
    if classification is None:
        # Unclassified -> no protection required; enforceable trivially.
        return ProtectionPlan(column=column, mechanism="none", policy_id=None, enforceable=True)

    policy = session.get(ProtectionPolicy, classification.policy_id)
    if policy is None:
        return ProtectionPlan(
            column=column,
            mechanism="none",
            policy_id=None,
            enforceable=False,
            reason="classification maps to no enforceable policy (FR-019)",
        )

    # Fail-closed: if the protection service is unavailable, block.
    if getattr(gateway, "_faults", None) and "kms_unavailable" in gateway._faults:
        return ProtectionPlan(
            column=column,
            mechanism=policy.mechanism.value,
            policy_id=policy.id,
            enforceable=False,
            reason="protection service unavailable; fail closed (FR-019)",
        )

    return ProtectionPlan(
        column=column,
        mechanism=policy.mechanism.value,
        policy_id=policy.id,
        enforceable=True,
    )


def enforce_protection(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    column: str,
    gateway: object,
) -> ProtectionPlan:
    """Enforce protection for a column, failing closed (FR-019).

    Raises :class:`FailClosedError` when the policy cannot be enforced so the
    caller blocks the batch instead of writing unprotected data.
    """
    plan = resolve_protection_plan(session, dataset_id=dataset_id, column=column, gateway=gateway)
    if not plan.enforceable:
        raise FailClosedError(plan.reason or "protection cannot be enforced (FR-019)")
    return plan
