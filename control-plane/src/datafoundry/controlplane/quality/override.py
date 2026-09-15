"""Override validation + expiry + audit (feature 004, T039, R-06).

- :func:`grant_override` — persist a granted bypass of a blocked gate with the
  full record (authorisation, reason, expiry, identity, timestamp, impact
  assessment) (FR-011). Incomplete overrides are rejected (FR-011); the
  override is scoped to the specific blocked run (FR-012).
- :func:`list_overrides` — read the audit history for a dataset (FR-012).
- :func:`get_override` — fetch a single override by id.
- :func:`is_override_active` — whether an override is active (not expired/
  revoked) for a report (FR-012).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.db.models import GateOverride, OverrideStatus
from datafoundry.controlplane.quality.security import scan_quality_text
from sqlalchemy import select
from sqlalchemy.orm import Session


class OverrideNotFoundError(KeyError):
    """Raised when an override id does not exist."""


class IncompleteOverrideError(ValueError):
    """Raised when an override is missing a required field (FR-011)."""


class OverrideExpiredError(RuntimeError):
    """Raised when an override has expired (FR-012)."""


#: Required fields for a valid override (FR-011).
_REQUIRED_FIELDS = (
    "authorising_identity",
    "reason",
    "expiry",
    "impact_assessment",
)


def grant_override(
    session: Session,
    *,
    report_id: uuid.UUID,
    dataset_id: uuid.UUID,
    authorising_identity: str,
    reason: str,
    expiry: datetime,
    impact_assessment: str,
    granted_by: str,
) -> GateOverride:
    """Persist an override for a blocked run (FR-011, FR-012).

    Validates all required fields (authorisation, reason, expiry, identity,
    timestamp, impact assessment); rejects incomplete overrides (FR-011).
    ``reason`` and ``impact_assessment`` are secret-scanned before persist
    (SC-007); detection raises :class:`QualitySecretLeakError` and nothing is
    stored.
    """
    _validate_required(
        authorising_identity=authorising_identity,
        reason=reason,
        expiry=expiry,
        impact_assessment=impact_assessment,
    )
    scan_quality_text(reason, field="reason")
    scan_quality_text(impact_assessment, field="impact_assessment")

    override = GateOverride(
        report_id=report_id,
        dataset_id=dataset_id,
        authorising_identity=authorising_identity,
        reason=reason,
        expiry=expiry,
        impact_assessment=impact_assessment,
        granted_at=datetime.now(UTC),
        status=OverrideStatus.active,
    )
    session.add(override)
    session.flush()
    return override


def _validate_required(**fields: Any) -> None:
    """Reject an override missing any required field (FR-011)."""
    missing = [name for name, value in fields.items() if value is None or value == ""]
    if missing:
        raise IncompleteOverrideError(f"override missing required field(s): {', '.join(missing)}")


def get_override(session: Session, override_id: uuid.UUID) -> GateOverride:
    """Fetch an override by id (FR-012 audit history)."""
    override = session.get(GateOverride, override_id)
    if override is None:
        raise OverrideNotFoundError(f"no override with id {override_id}")
    return override


def list_overrides(
    session: Session,
    *,
    dataset_id: uuid.UUID,
) -> list[GateOverride]:
    """List the override audit history for a dataset (FR-012).

    Active overrides whose ``expiry`` has passed are marked ``expired`` before
    listing, so the audit history reflects the true state (FR-012).
    """
    overrides = list(
        session.scalars(
            select(GateOverride)
            .where(GateOverride.dataset_id == dataset_id)
            .order_by(GateOverride.granted_at.desc())
        ).all()
    )
    now = datetime.now(UTC)
    for override in overrides:
        expiry = override.expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=UTC)
        if override.status == OverrideStatus.active and expiry <= now:
            override.status = OverrideStatus.expired
    if overrides:
        session.flush()
    return overrides


def is_override_active(session: Session, report_id: uuid.UUID) -> bool:
    """Whether an active override exists for a report (FR-012).

    An override is active iff its status is ``active`` and its ``expiry`` is in
    the future. Expired overrides are marked ``expired`` and audited.
    """
    override = session.execute(
        select(GateOverride)
        .where(GateOverride.report_id == report_id)
        .order_by(GateOverride.granted_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if override is None:
        return False
    now = datetime.now(UTC)
    expiry = override.expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=UTC)
    if override.status == OverrideStatus.active and expiry > now:
        return True
    if override.status == OverrideStatus.active and expiry <= now:
        override.status = OverrideStatus.expired
        session.flush()
    return False


__all__ = [
    "IncompleteOverrideError",
    "OverrideExpiredError",
    "OverrideNotFoundError",
    "get_override",
    "grant_override",
    "is_override_active",
    "list_overrides",
]
