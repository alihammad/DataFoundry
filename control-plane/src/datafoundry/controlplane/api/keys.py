"""API router: keys (T025, contracts/security-api.md §3).

- ``POST /keys`` — register a key reference (no material, FR-008): 201
  key_ref_id/version; 422 invalid kms / missing key_id / secret-scan.
- ``POST /keys/{id}/rotate`` — rotate to a new version (FR-009).
- ``POST /keys/{id}/revoke`` — revoke a key (FR-008).
- ``GET /keys/{id}`` — key reference status (never material).
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db, get_security_gateway
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.db.models import KmsProvider
from datafoundry.controlplane.security.keys import (
    KeyNotFoundError,
    get_key,
    register_key,
    revoke_key,
    rotate_key,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

router = APIRouter(tags=["keys"])


class KeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kms: str
    key_id: str
    version: int = 1
    rotation_schedule: str | None = None
    usage_permissions: list[str] = []


class KeyRegistered(BaseModel):
    key_ref_id: uuid.UUID
    version: int


class KeyRotated(BaseModel):
    key_ref_id: uuid.UUID
    version: int
    lifecycle_state: str


class KeyRevoked(BaseModel):
    lifecycle_state: str


class KeyStatus(BaseModel):
    key_ref_id: uuid.UUID
    kms: str
    key_id: str
    version: int
    lifecycle_state: str
    rotation_schedule: str | None
    usage_permissions: list[str]


def _get_key(session: Session, key_ref_id: uuid.UUID):
    try:
        return get_key(session, key_ref_id=key_ref_id)
    except KeyNotFoundError as exc:
        raise NotFoundError(f"no key reference with id {key_ref_id}") from exc


@router.post("/keys", status_code=201, response_model=KeyRegistered)
def register_key_endpoint(
    body: KeyRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    security_gateway: Any = Depends(get_security_gateway),
) -> KeyRegistered:
    """Register a key reference (no material, FR-008)."""
    try:
        kms = KmsProvider(body.kms)
    except ValueError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "kms",
                    "code": "invalid_value",
                    "message": f"invalid kms '{body.kms}'",
                    "remediation": "Use aws_kms or gcp_cloud_kms",
                }
            ]
        ) from exc
    if not body.key_id:
        raise ConfigValidationError(
            [
                {
                    "path": "key_id",
                    "code": "missing",
                    "message": "key_id is required (FR-008)",
                    "remediation": "Provide the KMS key id (never material)",
                }
            ]
        )
    from datafoundry.controlplane.config.secret_scan import scan_value

    findings = list(scan_value({"key_id": body.key_id}, "$"))
    if findings:
        raise ConfigValidationError(
            [
                {
                    "path": "key_id",
                    "code": "secret_scan",
                    "message": f"secret-scan: {f.path} ({f.kind})",
                    "remediation": "Key material must never be submitted (SC-003)",
                }
                for f in findings
            ]
        )
    key = register_key(
        session,
        kms=kms,
        key_id=body.key_id,
        version=body.version,
        rotation_schedule=body.rotation_schedule,
        usage_permissions=body.usage_permissions,
        gateway=security_gateway,
    )
    session.flush()
    return KeyRegistered(key_ref_id=key.id, version=key.version)


@router.post("/keys/{key_ref_id}/rotate", response_model=KeyRotated)
def rotate_key_endpoint(
    key_ref_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    security_gateway: Any = Depends(get_security_gateway),
) -> KeyRotated:
    """Rotate to a new version (FR-009)."""
    _get_key(session, key_ref_id)
    key = rotate_key(session, key_ref_id=key_ref_id, gateway=security_gateway)
    AuditService(session).security_key_rotate(
        actor=caller.identity, key_ref_id=key.id, version=key.version
    )
    session.flush()
    return KeyRotated(
        key_ref_id=key.id, version=key.version, lifecycle_state=key.lifecycle_state.value
    )


@router.post("/keys/{key_ref_id}/revoke", response_model=KeyRevoked)
def revoke_key_endpoint(
    key_ref_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    security_gateway: Any = Depends(get_security_gateway),
) -> KeyRevoked:
    """Revoke a key (FR-008)."""
    _get_key(session, key_ref_id)
    key = revoke_key(session, key_ref_id=key_ref_id, gateway=security_gateway)
    AuditService(session).security_key_revoke(actor=caller.identity, key_ref_id=key.id)
    session.flush()
    return KeyRevoked(lifecycle_state=key.lifecycle_state.value)


@router.get("/keys/{key_ref_id}", response_model=KeyStatus)
def get_key_status(
    key_ref_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> KeyStatus:
    """Key reference status (never material, FR-008)."""
    key = _get_key(session, key_ref_id)
    return KeyStatus(
        key_ref_id=key.id,
        kms=key.kms.value,
        key_id=key.key_id,
        version=key.version,
        lifecycle_state=key.lifecycle_state.value,
        rotation_schedule=key.rotation_schedule,
        usage_permissions=list(key.usage_permissions or []),
    )
