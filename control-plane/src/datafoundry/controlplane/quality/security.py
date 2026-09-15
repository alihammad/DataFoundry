"""Secret-scan wiring for quality write paths (T011, SC-007).

Every quality write/export path that can carry free-text or JSON payloads is
secret-scanned before persist: ``config_yaml``, ``metadata_json``,
``failure_reason``, ``impact_assessment`` (SC-007). Detection raises
:class:`QualitySecretLeakError` and nothing is stored (fail closed), mirroring
the feature 001 audit service.
"""

from __future__ import annotations

from typing import Any

from datafoundry.controlplane.config.secret_scan import (
    SecretFinding,
    scan_json_payload,
    scan_yaml_text,
)


class QualitySecretLeakError(RuntimeError):
    """Raised when a quality payload contains secret-like material (SC-007)."""

    def __init__(self, findings: list[SecretFinding]) -> None:
        self.findings = findings
        summary = ", ".join(f"{f.path}:{f.kind}" for f in findings)
        super().__init__(f"quality payload rejected — secret material detected ({summary})")


def scan_quality_yaml(yaml_text: str) -> None:
    """Secret-scan a gate config YAML document (SC-007)."""
    findings = scan_yaml_text(yaml_text)
    if findings:
        raise QualitySecretLeakError(findings)


def scan_quality_json(payload: dict[str, Any]) -> None:
    """Secret-scan a JSON payload (e.g. quarantine ``metadata_json``)."""
    findings = scan_json_payload(payload)
    if findings:
        raise QualitySecretLeakError(findings)


def scan_quality_text(text: str, *, field: str) -> None:
    """Secret-scan a free-text quality field (failure_reason, impact_assessment).

    Uses the JSON-payload scanner on a ``{field: text}`` wrapper so the field
    name is preserved in finding paths and the entropy heuristic applies.
    """
    findings = scan_json_payload({field: text})
    if findings:
        raise QualitySecretLeakError(findings)


__all__ = [
    "QualitySecretLeakError",
    "scan_quality_json",
    "scan_quality_text",
    "scan_quality_yaml",
]
