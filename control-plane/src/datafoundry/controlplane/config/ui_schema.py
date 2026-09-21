"""UI-owned Pydantic schemas (feature 007, T004/T008).

Strict schemas for saved queries, notification channels, and UI roles per
data-model.md. Unknown fields rejected; saved-query SQL and notification
config are secret-scanned on write (FR-022).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from datafoundry.controlplane.config.secret_scan import scan_text
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _reject_secrets(text: str) -> None:
    """Raise ValueError when secret-like material is detected (FR-022)."""
    findings = scan_text(text)
    if findings:
        raise ValueError(f"secret material detected: {', '.join(findings)}")


class SharingMode(StrEnum):
    private = "private"
    shared = "shared"


class ChannelType(StrEnum):
    email = "email"
    webhook = "webhook"
    slack = "slack"


class RoleScope(StrEnum):
    platform = "platform"
    dataset = "dataset"
    column = "column"


class ApprovalType(StrEnum):
    production_change = "production_change"
    override = "override"
    semantic_publication = "semantic_publication"
    contract = "contract"


class DecisionState(StrEnum):
    pending = "pending"
    approved = "approved"
    denied = "denied"


class SavedQueryCreate(BaseModel):
    """A user's stored SQL (data-model.md SavedQuery)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=127)
    sql_text: str = Field(min_length=1)
    dataset_bindings: list[str] = Field(default_factory=list)
    sharing: SharingMode = SharingMode.private

    @field_validator("sql_text")
    @classmethod
    def _secret_scan_sql(cls, v: str) -> str:
        _reject_secrets(v)
        return v


class SavedQueryShareCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shared_with_identity: str = Field(min_length=1, max_length=256)


class NotificationChannelCreate(BaseModel):
    """Per-platform alert routing (data-model.md NotificationChannel)."""

    model_config = ConfigDict(extra="forbid")

    platform_id: str
    channel_type: ChannelType
    name: str = Field(min_length=1, max_length=63)
    config: dict = Field(default_factory=dict)
    event_types: list[str] = Field(default_factory=list)
    enabled: bool = True

    @field_validator("config")
    @classmethod
    def _secret_scan_config(cls, v: dict) -> dict:
        _reject_secrets(str(v))
        return v


class NotificationChannelUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, max_length=63)
    config: dict | None = None
    event_types: list[str] | None = None
    enabled: bool | None = None

    @field_validator("config")
    @classmethod
    def _secret_scan_config(cls, v: dict | None) -> dict | None:
        if v is not None:
            _reject_secrets(str(v))
        return v


class DatasetScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    columns: list[str] = Field(default_factory=list)


class UIRoleCreate(BaseModel):
    """RBAC permission set (data-model.md UIRole)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=63)
    scope: RoleScope
    permissions: list[str] = Field(default_factory=list)
    platform_scope: list[str] = Field(default_factory=list)
    dataset_scope: list[DatasetScope] = Field(default_factory=list)


class UIRoleAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_identity: str = Field(min_length=1, max_length=256)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approved", "denied"]
    reasoning: str = Field(min_length=1)
