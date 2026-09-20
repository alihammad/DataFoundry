"""Classification module (feature 005, T008).

Classification levels (PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED/
HIGHLY_RESTRICTED), org-defined classification->policy mapping, and downgrade
authorisation (FR-020).
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.db.models import Classification, SecurityLevel
from sqlalchemy import select
from sqlalchemy.orm import Session

#: Ordered sensitivity levels (index = rank; higher = more sensitive).
LEVEL_ORDER: list[SecurityLevel] = [
    SecurityLevel.public,
    SecurityLevel.internal,
    SecurityLevel.confidential,
    SecurityLevel.restricted,
    SecurityLevel.highly_restricted,
]


def level_rank(level: SecurityLevel) -> int:
    """The sensitivity rank of a level (higher = more sensitive)."""
    return LEVEL_ORDER.index(level)


def is_downgrade(current: SecurityLevel | None, proposed: SecurityLevel) -> bool:
    """Whether ``proposed`` is less sensitive than ``current`` (FR-020)."""
    if current is None:
        return False
    return level_rank(proposed) < level_rank(current)


def set_classification(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    level: SecurityLevel,
    policy_id: uuid.UUID,
    changed_by: str,
    column: str | None = None,
) -> Classification:
    """Set a dataset/column classification (FR-001, FR-020).

    Downgrades require authorisation (checked by the caller) and are audited;
    they apply to subsequent processing only (never retroactively expose
    already-protected data).
    """
    existing = session.execute(
        select(Classification).where(
            Classification.dataset_id == dataset_id,
            Classification.column == column,
        )
    ).scalar_one_or_none()
    if existing is not None:
        # Record the prior level for lineage (FR-018) BEFORE overwriting.
        existing.previous_level = existing.level
        existing.level = level
        existing.policy_id = policy_id
        existing.changed_by = changed_by
        session.flush()
        return existing
    row = Classification(
        dataset_id=dataset_id,
        level=level,
        column=column,
        policy_id=policy_id,
        changed_by=changed_by,
    )
    session.add(row)
    session.flush()
    return row


def get_classification(
    session: Session, *, dataset_id: uuid.UUID, column: str | None = None
) -> Classification | None:
    """The classification for a dataset (or a specific column)."""
    return session.execute(
        select(Classification).where(
            Classification.dataset_id == dataset_id,
            Classification.column == column,
        )
    ).scalar_one_or_none()
