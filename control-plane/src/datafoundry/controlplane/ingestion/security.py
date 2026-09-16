"""Secret-scan wiring for ingestion write/export paths (T012, SC-007).

Every ingestion write/export path (config_ref, config_yaml, metadata_json,
failure_reason, log_ref) must be secret-scanned before persist and redacted
before it reaches logs or the UI. This module centralises the helpers.
"""

from __future__ import annotations

from typing import Any

from datafoundry.controlplane.config.secret_scan import (
    SecretFinding,
    has_secrets,
    redact,
    scan_value,
    scan_yaml_text,
)


def scan_ingestion_payload(payload: Any, path: str = "$") -> list[SecretFinding]:
    """Scan an ingestion payload (config_ref, metadata_json, etc.)."""
    return scan_value(payload, path)


def scan_ingestion_yaml(yaml_text: str) -> list[SecretFinding]:
    """Scan canonical ingestion config YAML."""
    return scan_yaml_text(yaml_text)


def reject_secrets(payload: Any, *, what: str) -> None:
    """Raise ValueError if a payload contains secret material (SC-007)."""
    if has_secrets(payload):
        raise ValueError(f"{what} contains secret material; use a secretRef pointer")


def redact_ingestion(value: Any) -> Any:
    """Deep-redact an ingestion payload for safe logging/serialisation."""
    return redact(value)
