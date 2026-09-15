"""Secret-scan pass (T010).

Applied to config YAML, audit payloads, error details, and exports before
they are stored or returned (SC-006, R-09). Detects:

- AWS access key ids / secret access keys / session tokens
- GCP API keys and service-account key JSON fragments
- Private key material (PEM blocks)
- High-entropy strings (heuristic)

Also provides ``redact`` for log/response sanitisation.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: (name, compiled pattern) pairs for known secret shapes.
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "aws_access_key_id",
        re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"),
    ),
    (
        "aws_secret_access_key",
        re.compile(
            r"(?i)aws[_-]?(?:secret[_-]?)?(?:access[_-]?)?key[_-]?\s*(?:[:=]|is)\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"
        ),
    ),
    (
        "gcp_api_key",
        re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    ),
    (
        "gcp_service_account_key",
        re.compile(r'"type"\s*:\s*"service_account"'),
    ),
    (
        "private_key_pem",
        re.compile(
            r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"
        ),
    ),
    (
        "generic_secret_assignment",
        re.compile(
            r"(?i)\b(?:secret|passwd|password|token|api[_-]?key|access[_-]?key|private[_-]?key)\b"
            r"\s*(?:[:=]|is)\s*['\"]?([^\s'\"]{16,})['\"]?"
        ),
    ),
)

#: Substring that replaces detected secret material in redacted output.
REDACTION = "[REDACTED]"

#: Shannon entropy threshold (bits/char) for the high-entropy heuristic.
ENTROPY_THRESHOLD = 4.5
#: Minimum token length considered for the entropy heuristic.
ENTROPY_MIN_LENGTH = 20

#: Field-name fragments that legitimately carry long opaque values (hashes,
#: refs, ids) and are exempt from the entropy heuristic.
_ENTROPY_ALLOWLISTED_FIELDS = frozenset(
    {
        "config_hash",
        "hash",
        "sha256",
        "digest",
        "git_ref",
        "ref",
        "kms_key_ref",
        "id",
        "platform_id",
        "run_id",
        "check_id",
        "resource_ids",
        "approval_ref",
        "trace_id",
        "span_id",
        # SQL expressions / queries are legitimate long strings (quality tests).
        "sql",
        "expression",
    }
)


@dataclass(frozen=True)
class SecretFinding:
    """One detected secret-like value."""

    path: str
    kind: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "kind": self.kind, "message": self.message}


def shannon_entropy(value: str) -> float:
    """Shannon entropy in bits per character."""
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for ch in value:
        counts[ch] = counts.get(ch, 0) + 1
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def _looks_like_secret_token(value: str) -> bool:
    """High-entropy heuristic: long token mixing case/digits/symbols."""
    if len(value) < ENTROPY_MIN_LENGTH:
        return False
    has_lower = any(c.islower() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_digit = any(c.isdigit() for c in value)
    mixed_classes = sum([has_lower, has_upper, has_digit]) >= 2
    if not mixed_classes and not re.search(r"[/+=_\-]", value):
        return False
    return shannon_entropy(value) >= ENTROPY_THRESHOLD


def scan_text(text: str) -> list[str]:
    """Return the kinds of known secret patterns found in ``text``."""
    found: list[str] = []
    for name, pattern in SECRET_PATTERNS:
        if pattern.search(text):
            found.append(name)
    return found


def scan_value(value: Any, path: str = "$") -> list[SecretFinding]:
    """Recursively scan a parsed config/payload structure for secret material.

    Walks mappings and sequences; strings are checked against known patterns
    and the entropy heuristic (field-name allowlist suppresses false positives
    on hashes/refs).
    """
    findings: list[SecretFinding] = []

    if isinstance(value, Mapping):
        for key, item in value.items():
            findings.extend(scan_value(item, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            findings.extend(scan_value(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        field_name = path.rsplit(".", 1)[-1].split("[", 1)[0]
        for kind in scan_text(value):
            findings.append(
                SecretFinding(
                    path=path,
                    kind=kind,
                    message=f"Value at '{path}' matches secret pattern '{kind}'",
                )
            )
        if (
            not findings
            and field_name not in _ENTROPY_ALLOWLISTED_FIELDS
            and _looks_like_secret_token(value)
        ):
            findings.append(
                SecretFinding(
                    path=path,
                    kind="high_entropy_string",
                    message=(
                        f"Value at '{path}' looks like a high-entropy secret; "
                        "use a secretRef pointer instead (SC-006)"
                    ),
                )
            )
    return findings


def scan_config_dict(config: Mapping[str, Any]) -> list[SecretFinding]:
    """Scan a parsed platform-config mapping (validation rule 7)."""
    return scan_value(config, "$")


def scan_yaml_text(yaml_text: str) -> list[SecretFinding]:
    """Scan raw YAML text for secret patterns (used for exports/audit payloads)."""
    findings = [
        SecretFinding(path="$", kind=kind, message=f"Document matches secret pattern '{kind}'")
        for kind in scan_text(yaml_text)
    ]
    try:
        import yaml  # local import: keeps module import-light

        parsed = yaml.safe_load(yaml_text)
    except Exception:  # unparseable text still pattern-scanned above
        return findings
    if parsed is not None:
        findings.extend(scan_value(parsed, "$"))
    return findings


def scan_json_payload(payload: Any) -> list[SecretFinding]:
    """Scan an audit/API JSON payload (must be JSON-serialisable)."""
    return scan_value(payload, "$")


def has_secrets(value: Any) -> bool:
    """True when any secret-like material is detected."""
    if isinstance(value, str):
        return bool(scan_text(value)) or _looks_like_secret_token(value)
    return bool(scan_value(value))


def redact_text(text: str) -> str:
    """Replace detected secret material with ``[REDACTED]`` (logs, R-09)."""
    redacted = text
    for _, pattern in SECRET_PATTERNS:
        redacted = pattern.sub(REDACTION, redacted)
    return redacted


def redact(value: Any) -> Any:
    """Deep-redact a JSON-like structure for safe logging/serialisation."""
    if isinstance(value, Mapping):
        return {k: redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_json(payload: Any) -> str:
    """Serialise ``payload`` to JSON with secret patterns redacted."""
    return json.dumps(redact(payload), default=str, sort_keys=True)
