"""Config export service (T069, FR-011, SC-006).

Serialises a platform's stored configuration as canonical YAML (sorted keys,
normalised whitespace — reuse ``config/validation.canonical_yaml``) with a
SHA-256 ``config_hash``, and guarantees no plaintext secrets leave the
service: every export runs the secret-scan pass (``scan_yaml_text``) and
fails closed (raises) rather than returning a contaminated document.

The config is immutable once versioned (T070), so the export is always a
byte-for-byte reproduction of the stored version snapshot.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from datafoundry.controlplane.config.secret_scan import scan_yaml_text
from datafoundry.controlplane.config.validation import config_hash
from datafoundry.controlplane.db.models import Platform, PlatformConfigVersion
from sqlalchemy.orm import Session


class ExportSecretLeakError(RuntimeError):
    """Raised when a stored config contains secret material (SC-006 fail closed)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class ExportedConfig:
    """The exported configuration document (deployment-api.md §1)."""

    version: int
    config_yaml: str
    config_hash: str  # sha256:<hex> per the API contract
    git_ref: str | None

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "config_yaml": self.config_yaml,
            "config_hash": self.config_hash,
            "git_ref": self.git_ref,
        }


def load_version(session: Session, version_id: uuid.UUID) -> PlatformConfigVersion:
    version = session.get(PlatformConfigVersion, version_id)
    if version is None:
        raise KeyError(f"config version {version_id} not found")
    return version


def export_version(session: Session, version: PlatformConfigVersion) -> ExportedConfig:
    """Export one config version with the secret-scan guarantee (SC-006)."""
    yaml_text = version.config_yaml
    findings = scan_yaml_text(yaml_text)
    if findings:
        summary = ", ".join(f"{f.path}:{f.kind}" for f in findings)
        raise ExportSecretLeakError(
            f"stored config contains secret material — export refused ({summary})"
        )
    return ExportedConfig(
        version=version.version,
        config_yaml=yaml_text,
        config_hash=f"sha256:{version.config_hash}",
        git_ref=version.git_ref,
    )


def export_platform(
    session: Session, platform: Platform, *, version: PlatformConfigVersion | None = None
) -> ExportedConfig:
    """Export a platform's current (or a specific) config version."""
    target = version
    if target is None:
        if platform.current_config_version_id is None:
            raise KeyError(f"platform {platform.id} has no recorded config version")
        target = load_version(session, platform.current_config_version_id)
    return export_version(session, target)


def export_config_hash(raw_config: dict) -> str:
    """``sha256:<hex>`` form of the canonical config hash (API contract)."""
    return f"sha256:{config_hash(raw_config)}"
