"""Logical encryption service (feature 005, T011).

Key reference model, rotation/versioning/revocation; keys never stored or
exposed (FR-008, FR-009, FR-010).
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.db.models import (
    KeyLifecycleState,
    KeyReference,
    KmsProvider,
)
from sqlalchemy.orm import Session


class KeyNotFoundError(KeyError):
    """Raised when a key reference id does not exist."""


def register_key(
    session: Session,
    *,
    kms: KmsProvider,
    key_id: str,
    version: int,
    rotation_schedule: str | None,
    usage_permissions: list[str],
    gateway: object,
) -> KeyReference:
    """Register a key reference (no material, FR-008)."""
    key = KeyReference(
        kms=kms,
        key_id=key_id,
        version=version,
        lifecycle_state=KeyLifecycleState.active,
        rotation_schedule=rotation_schedule,
        usage_permissions=usage_permissions,
    )
    session.add(key)
    session.flush()
    # Material lives in the KMS (in-memory in the simulated gateway).
    gateway.create_key(str(key.id), version=version)
    return key


def get_key(session: Session, *, key_ref_id: uuid.UUID) -> KeyReference:
    """Fetch a key reference (never material, FR-008)."""
    key = session.get(KeyReference, key_ref_id)
    if key is None:
        raise KeyNotFoundError(f"no key reference with id {key_ref_id}")
    return key


def rotate_key(session: Session, *, key_ref_id: uuid.UUID, gateway: object) -> KeyReference:
    """Rotate to a new version; prior versions stay readable (FR-009)."""
    key = get_key(session, key_ref_id=key_ref_id)
    new_version = gateway.rotate_key(str(key.id))
    key.version = new_version
    key.lifecycle_state = KeyLifecycleState.active
    session.flush()
    return key


def revoke_key(session: Session, *, key_ref_id: uuid.UUID, gateway: object) -> KeyReference:
    """Revoke the current version; blocks further decryption (FR-008)."""
    key = get_key(session, key_ref_id=key_ref_id)
    gateway.revoke_key(str(key.id))
    key.lifecycle_state = KeyLifecycleState.revoked
    session.flush()
    return key
