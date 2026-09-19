"""Token service (feature 005, T012).

Deterministic + random tokenisation; originals only in the secured token
service (FR-011); detokenisation requires authorisation + purpose (FR-012).
"""

from __future__ import annotations

import hashlib
import uuid

from datafoundry.controlplane.db.models import TokenReference
from sqlalchemy import select
from sqlalchemy.orm import Session


class TokenNotFoundError(KeyError):
    """Raised when a token does not exist."""


def tokenise(
    session: Session,
    *,
    dataset_id: uuid.UUID,
    column: str,
    value: str,
    deterministic: bool,
    token_service_ref: str,
    gateway: object,
) -> str:
    """Tokenise a value (FR-011).

    Deterministic mode maps identical inputs to identical tokens (keeps
    joins/matching possible without exposing values). Originals are kept only
    in the secured token service (the gateway's in-memory vault).
    """
    token = gateway.tokenise(value=value, deterministic=deterministic)
    original_hash = hashlib.sha256(value.encode()).hexdigest()
    session.add(
        TokenReference(
            dataset_id=dataset_id,
            column=column,
            token=token,
            original_hash=original_hash,
            deterministic=deterministic,
            token_service_ref=token_service_ref,
        )
    )
    session.flush()
    return token


def detokenise(
    session: Session,
    *,
    token: str,
    gateway: object,
) -> str:
    """Detokenise a token back to its original value (FR-012).

    Authorisation + purpose are enforced by the caller (API layer); this
    function performs the vault lookup.
    """
    ref = session.execute(
        select(TokenReference).where(TokenReference.token == token)
    ).scalar_one_or_none()
    if ref is None:
        raise TokenNotFoundError(f"no token {token}")
    return gateway.detokenise(token=token)
