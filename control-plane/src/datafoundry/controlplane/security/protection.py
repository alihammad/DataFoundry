"""Column-level protection engine (feature 005, T010).

Registry of six mechanisms (encrypt/tokenise/mask/hash/redact/pseudonymise),
each returning protected value + status (R-02).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass
class ProtectionResult:
    """Output of a protection mechanism: value + status."""

    value: Any
    status: str  # protected | unchanged


class ProtectionMechanismError(RuntimeError):
    """Raised when a protection mechanism cannot be applied (fail-closed)."""


def _mask(value: Any, rule: dict[str, Any] | None) -> str:
    text = str(value)
    show_first = int((rule or {}).get("show_first", 0))
    show_last = int((rule or {}).get("show_last", 0))
    if show_first + show_last >= len(text):
        return text
    head = text[:show_first]
    tail = text[-show_last:] if show_last else ""
    return head + "*" * (len(text) - show_first - show_last) + tail


def _hash(value: Any) -> str:
    return hashlib.sha256(str(value).encode()).hexdigest()


def _redact(_value: Any) -> str:
    return "[REDACTED]"


def _pseudonymise(value: Any) -> str:
    digest = hashlib.sha256(str(value).encode()).hexdigest()[:12]
    return f"pseudo_{digest}"


#: Mechanism -> callable(value, *, gateway, policy) -> ProtectionResult.
_MECHANISMS: dict[str, Callable[..., ProtectionResult]] = {}


def _register(name: str, fn: Callable[..., ProtectionResult]) -> None:
    _MECHANISMS[name] = fn


def _encrypt(value: Any, *, gateway, policy) -> ProtectionResult:
    key_ref_id = getattr(policy, "key_ref_id", None) if policy else None
    if not key_ref_id:
        raise ProtectionMechanismError("encrypt requires key_ref_id (FR-008)")
    version = gateway.key_version(key_ref_id)
    ciphertext = gateway.encrypt(key_ref_id=key_ref_id, version=version, value=str(value))
    return ProtectionResult(value=ciphertext, status="protected")


def _tokenise(value: Any, *, gateway, policy) -> ProtectionResult:
    key_ref_id = getattr(policy, "key_ref_id", None) if policy else None
    if not key_ref_id:
        raise ProtectionMechanismError("tokenise requires key_ref_id (FR-008)")
    token = gateway.tokenise(value=str(value), deterministic=True)
    return ProtectionResult(value=token, status="protected")


def _mask_mech(value: Any, *, gateway, policy) -> ProtectionResult:
    rule = getattr(policy, "masking_rule", None) if policy else None
    return ProtectionResult(value=_mask(value, rule), status="protected")


def _hash_mech(value: Any, *, gateway, policy) -> ProtectionResult:
    return ProtectionResult(value=_hash(value), status="protected")


def _redact_mech(value: Any, *, gateway, policy) -> ProtectionResult:
    return ProtectionResult(value=_redact(value), status="protected")


def _pseudonymise_mech(value: Any, *, gateway, policy) -> ProtectionResult:
    return ProtectionResult(value=_pseudonymise(value), status="protected")


_register("encrypt", _encrypt)
_register("tokenise", _tokenise)
_register("mask", _mask_mech)
_register("hash", _hash_mech)
_register("redact", _redact_mech)
_register("pseudonymise", _pseudonymise_mech)


def protect_value(*, value: Any, mechanism: str, gateway: Any, policy: Any) -> ProtectionResult:
    """Apply a protection mechanism to a value (R-02).

    Raises :class:`ProtectionMechanismError` when the mechanism is unknown or
    cannot be applied (fail-closed, FR-019).
    """
    fn = _MECHANISMS.get(mechanism)
    if fn is None:
        raise ProtectionMechanismError(f"unknown protection mechanism '{mechanism}'")
    return fn(value, gateway=gateway, policy=policy)


def mechanisms() -> list[str]:
    """The registered protection mechanisms."""
    return sorted(_MECHANISMS)
