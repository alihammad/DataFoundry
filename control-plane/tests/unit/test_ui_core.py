"""Unit tests for feature 007 UI foundational core (T013).

Covers UI schema conformance vs data-model.md, secret-scan on saved-query SQL
and notification config, UI audit actions, and the API client's problem+json
parsing (frontend side).
"""

from __future__ import annotations

import pytest
from datafoundry.controlplane.config.ui_schema import (
    NotificationChannelCreate,
    SavedQueryCreate,
    UIRoleCreate,
)
from pydantic import ValidationError


class TestSavedQuerySchema:
    def test_valid(self):
        q = SavedQueryCreate(
            name="revenue",
            sql_text="SELECT * FROM gold_orders",
            dataset_bindings=["gold_orders"],
            sharing="private",
        )
        assert q.name == "revenue"
        assert q.sharing == "private"

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            SavedQueryCreate(name="x", sql_text="SELECT 1", bogus=1)

    def test_secret_scan_rejects_secret_in_sql(self):
        with pytest.raises(ValidationError):
            SavedQueryCreate(
                name="leak",
                sql_text="SELECT * FROM t WHERE key='AKIAIOSFODNN7EXAMPLE'",
            )


class TestNotificationChannelSchema:
    def test_valid(self):
        ch = NotificationChannelCreate(
            platform_id="p1",
            channel_type="email",
            name="ops",
            config={"recipients": ["ops@example.com"]},
            event_types=["gate.failed"],
        )
        assert ch.channel_type == "email"
        assert ch.enabled is True

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            NotificationChannelCreate(platform_id="p1", channel_type="email", name="x", nope=1)

    def test_secret_scan_rejects_secret_in_config(self):
        with pytest.raises(ValidationError):
            NotificationChannelCreate(
                platform_id="p1",
                channel_type="webhook",
                name="x",
                config={"url": "https://x", "token": "AKIAIOSFODNN7EXAMPLE"},
            )


class TestUIRoleSchema:
    def test_valid(self):
        role = UIRoleCreate(
            name="analyst",
            scope="dataset",
            permissions=["dataset.read"],
            dataset_scope=[{"dataset_id": "d1", "columns": ["customer_id"]}],
        )
        assert role.scope == "dataset"

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            UIRoleCreate(name="x", scope="platform", bogus=1)


class TestUIAuditActions:
    def test_ui_actions_recorded(self, session, ui_caller):
        from datafoundry.controlplane.audit.service import AuditService

        svc = AuditService(session)
        svc.ui_saved_query_created(
            actor=ui_caller.identity, query_id="q1", name="r", sharing="private"
        )
        svc.ui_role_created(actor=ui_caller.identity, role_id="r1", name="analyst", scope="dataset")
        svc.ui_approval_decided(
            actor=ui_caller.identity,
            approval_id="a1",
            approval_type="override",
            decision="approved",
        )
        session.flush()

        from datafoundry.controlplane.db.models import AuditRecord

        actions = {r.action for r in session.query(AuditRecord).all()}
        assert "ui.saved_query.created" in actions
        assert "ui.role.created" in actions
        assert "ui.approval.decided" in actions


class TestUISecurity:
    """Security hardening (feature 007, T050): no secrets leak through UI paths."""

    def test_notification_config_never_returned(self, client):
        """FR-022/SC-006: channel config (may hold credentials) is never returned."""
        from pathlib import Path

        import yaml

        examples = Path(__file__).resolve().parents[3] / "platform-configs" / "examples"
        config = yaml.safe_load((examples / "dev-aws-sandbox.yaml").read_text())
        pid = client.post("/api/v1/platforms", json={"config": config}).json()["platform_id"]
        client.post(
            "/api/v1/ui/notifications",
            json={
                "platform_id": pid,
                "channel_type": "webhook",
                "name": "ops",
                "config": {"url": "https://hooks.example.com", "token": "secret-token"},
                "event_types": ["gate.failed"],
            },
        )
        items = client.get("/api/v1/ui/notifications").json()["items"]
        assert all("config" not in item for item in items)
        assert all("token" not in str(item) for item in items)

    def test_saved_query_secret_scan_blocks_secret(self, client):
        """FR-022: saved-query SQL with a secret is rejected."""
        resp = client.post(
            "/api/v1/ui/saved-queries",
            json={"name": "leak", "sql_text": "SELECT 'AKIAIOSFODNN7EXAMPLE'"},
        )
        assert resp.status_code == 422
