"""PlatformConfigVersion lifecycle (T070, SC-002).

Immutable versioned snapshots: every config change creates a new version
(incrementing per platform). Deploying an identical config is idempotent —
if the incoming ``config_hash`` equals the platform's current version hash,
no new version is created and no new run is queued (SC-002 reproducibility +
idempotency). Provenance (``source`` api/cli/git + ``git_ref``) is recorded
on every version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datafoundry.controlplane.config.secret_scan import scan_config_dict
from datafoundry.controlplane.config.validation import canonical_yaml, config_hash
from datafoundry.controlplane.db.models import (
    ConfigSource,
    Platform,
    PlatformConfigVersion,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


class VersioningSecretLeakError(RuntimeError):
    """Raised when a config to version contains secret material (SC-006)."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class VersionOutcome:
    """Result of versioning an incoming config."""

    version: PlatformConfigVersion
    created: bool  # False => identical config_hash, version reused (idempotent)


def _scan_or_raise(raw_config: dict) -> None:
    findings = scan_config_dict(raw_config)
    if findings:
        summary = ", ".join(f"{f.path}:{f.kind}" for f in findings)
        raise VersioningSecretLeakError(
            f"config contains secret material — version refused ({summary})"
        )


def current_version_hash(session: Session, platform_id) -> str | None:
    stmt = (
        select(PlatformConfigVersion.config_hash)
        .where(PlatformConfigVersion.platform_id == platform_id)
        .order_by(PlatformConfigVersion.version.desc())
        .limit(1)
    )
    return session.execute(stmt).scalar_one_or_none()


def next_version_number(session: Session, platform_id) -> int:
    stmt = (
        select(PlatformConfigVersion.version)
        .where(PlatformConfigVersion.platform_id == platform_id)
        .order_by(PlatformConfigVersion.version.desc())
        .limit(1)
    )
    current = session.execute(stmt).scalar_one_or_none()
    return (current or 0) + 1


def version_config(
    session: Session,
    *,
    platform: Platform,
    raw_config: dict[str, Any],
    created_by: str,
    source: ConfigSource = ConfigSource.api,
    git_ref: str | None = None,
) -> VersionOutcome:
    """Create a new immutable version, or return the existing one when the
    config is byte-identical (idempotent deploy, SC-002)."""
    _scan_or_raise(raw_config)
    incoming_hash = config_hash(raw_config)

    existing = current_version_hash(session, platform.id)
    if existing == incoming_hash:
        stmt = (
            select(PlatformConfigVersion)
            .where(
                PlatformConfigVersion.platform_id == platform.id,
                PlatformConfigVersion.config_hash == incoming_hash,
            )
            .order_by(PlatformConfigVersion.version.desc())
            .limit(1)
        )
        reused = session.execute(stmt).scalar_one()
        return VersionOutcome(version=reused, created=False)

    version = PlatformConfigVersion(
        platform_id=platform.id,
        version=next_version_number(session, platform.id),
        config_yaml=canonical_yaml(raw_config),
        config_hash=incoming_hash,
        source=source,
        git_ref=git_ref,
        created_by=created_by,
    )
    session.add(version)
    session.flush()
    platform.current_config_version_id = version.id
    session.flush()
    return VersionOutcome(version=version, created=True)
