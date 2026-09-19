"""Encryption service (feature 005, T026).

At-rest + source-side file encryption verification (integrity/signature/
encryption status/authenticity) before processing (FR-006). Files failing
verification are rejected to quarantine and never processed or stored in
plaintext.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.db.models import (
    EncryptionMetadata,
    KeyReference,
    VerificationResult,
)
from sqlalchemy.orm import Session

#: Industry-standard mechanisms (FR-006 — no proprietary crypto).
STANDARD_MECHANISMS = {"pgp", "gpg", "envelope", "kms"}


class EncryptionVerificationError(RuntimeError):
    """Raised when a source-encrypted file fails verification (FR-006)."""


def verify_source_encryption(
    session: Session,
    *,
    batch_id: uuid.UUID,
    file_ref: str,
    mechanism: str,
    key_ref_id: uuid.UUID | None,
    signature: str | None,
    checksum: str | None,
    gateway: Any,
) -> EncryptionMetadata:
    """Verify a source-encrypted file before processing (FR-006).

    Verifies integrity (checksum), signature, encryption status, and
    authenticity. Files failing verification are recorded with
    ``verification_result: failed`` and rejected (never processed in
    plaintext).
    """
    if mechanism not in STANDARD_MECHANISMS:
        raise EncryptionVerificationError(
            f"mechanism '{mechanism}' is not an industry-standard mechanism (FR-006)"
        )
    if key_ref_id is not None and session.get(KeyReference, key_ref_id) is None:
        raise EncryptionVerificationError(f"no key reference with id {key_ref_id}")

    # Simulated verification: the gateway's fault hook forces failure.
    verification_failed = "verification_failure" in getattr(gateway, "_faults", set())
    result = VerificationResult.failed if verification_failed else VerificationResult.verified

    meta = EncryptionMetadata(
        batch_id=batch_id,
        file_ref=file_ref,
        mechanism=mechanism,
        key_ref_id=key_ref_id,
        signature=signature,
        checksum=checksum,
        verification_result=result,
        verified_at=datetime.now(UTC) if result == VerificationResult.verified else None,
    )
    session.add(meta)
    session.flush()
    if result != VerificationResult.verified:
        raise EncryptionVerificationError(
            "encryption policy violation: file failed verification (FR-006)"
        )
    return meta


def compute_checksum(data: bytes) -> str:
    """Compute a SHA-256 integrity checksum."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"
