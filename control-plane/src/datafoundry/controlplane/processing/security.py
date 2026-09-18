"""Secret-scan wiring for processing write/export paths (feature 003, T011).

``logic_definition``, ``metadata_json``, and ``blocked_reason`` must be
secret-scanned before persist and redacted of secret patterns (SC-007).
"""

from __future__ import annotations

from typing import Any

from datafoundry.controlplane.config.secret_scan import (
    SecretFinding,
    has_secrets,
    redact,
    scan_value,
)


def scan_processing_payload(payload: Any, path: str = "$") -> list[SecretFinding]:
    """Scan a processing payload for secret material (SC-007)."""
    return list(scan_value(payload, path))


def reject_secrets(payload: Any, *, what: str) -> None:
    """Raise ValueError if a payload contains secret material (SC-007)."""
    if has_secrets(payload):
        raise ValueError(f"{what} contains secret material; use a secretRef pointer")


def redact_processing(value: Any) -> Any:
    """Redact secret patterns from a value (SC-007)."""
    return redact(value)
