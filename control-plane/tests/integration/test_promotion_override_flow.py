"""T035: Integration test for quickstart Scenario 4 (US4, FR-007/FR-008).

Attempt promotion on a failed critical gate -> refused + BLOCKED; grant
override -> promotion proceeds + auditable; incomplete override rejected;
expired override grants no permission.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pyarrow as pa


def _seed_platform(app):
    from datafoundry.controlplane.db.models import (
        EnvironmentType,
        Platform,
        Provider,
    )

    with app.state.sessionmaker() as sess:
        platform = Platform(
            name="crm-platform",
            provider=Provider.aws,
            cloud_scope_id="scope-1",
            region="us-east-1",
            environment_type=EnvironmentType.test,
            owner_identity="dev@datafoundry.local",
        )
        sess.add(platform)
        sess.commit()
        return platform.id


def _register_dataset(app, client, platform_id, name, layer, schema):
    body = {
        "platform_id": str(platform_id),
        "name": name,
        "layer": layer,
        "schema_definition": schema,
        "owner_identity": "dev@datafoundry.local",
        "classification": "internal",
    }
    response = client.post("/api/v1/datasets", json=body)
    assert response.status_code == 201, response.text
    return response.json()["dataset_id"]


def _define_silver_transform(client):
    body = {
        "name": "customer_silver_transform",
        "source_layer": "bronze",
        "target_layer": "silver",
        "dedup_keys": ["customer_id"],
        "logic": {
            "type": "silver",
            "cleansing": [{"column": "email", "op": "trim"}],
            "standardisation": [],
            "schema_enforcement": {
                "customer_id": {"type": "integer", "nullable": False},
                "email": {"type": "string", "nullable": False},
            },
        },
    }
    response = client.post("/api/v1/transformations", json=body)
    assert response.status_code == 201, response.text
    return response.json()["transformation_id"]


def _define_failing_gate(app, dataset_id):
    """Define a gate with a critical uniqueness test that fails on duplicates."""
    from datafoundry.controlplane.db.models import (
        LayerTransition,
        QualityGate,
        QualityTest,
        TestCategory,
        TestSeverity,
    )

    with app.state.sessionmaker() as sess:
        gate = QualityGate(
            dataset_id=uuid.UUID(dataset_id),
            transition=LayerTransition.bronze_to_silver,
            config_version=1,
            config_yaml="{}",
            config_hash="a" * 64,
            created_by="dev@datafoundry.local",
        )
        sess.add(gate)
        sess.flush()
        sess.add(
            QualityTest(
                gate_id=gate.id,
                name="unique_customer_id",
                category=TestCategory.uniqueness,
                severity=TestSeverity.critical,
                parameters={"columns": ["customer_id"]},
                owner_identity="dev@datafoundry.local",
            )
        )
        sess.commit()
        return gate.id


class TestScenario4PromotionOverride:
    def test_failed_gate_blocks_then_override_promotes(self, app, client):
        platform_id = _seed_platform(app)
        bronze_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        }
        silver_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        }
        bronze_id = _register_dataset(
            app, client, platform_id, "customer_bronze", "bronze", bronze_schema
        )
        silver_id = _register_dataset(
            app, client, platform_id, "customer_silver", "silver", silver_schema
        )
        transformation_id = _define_silver_transform(client)
        _define_failing_gate(app, silver_id)

        # Bronze with duplicate customer_id -> uniqueness gate fails.
        app.state.processing_gateway.seed_table(
            bronze_id,
            "bronze",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("email", pa.string()),
                ]
            ),
            [
                {"customer_id": 1, "email": "a@example.com"},
                {"customer_id": 1, "email": "a@example.com"},
            ],
        )
        # The quality gate reads the silver zone via the quality gateway.
        app.state.quality_gateway.seed_table(
            silver_id,
            "silver",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("email", pa.string()),
                ]
            ),
            [
                {"customer_id": 1, "email": "a@example.com"},
                {"customer_id": 1, "email": "a@example.com"},
            ],
        )

        # First run: gate fails -> BLOCKED (FR-007, US4-AC1).
        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["promotion_state"] == "blocked"
        assert data["gate_report_id"]

        status = client.get(f"/api/v1/datasets/{silver_id}/promotion").json()
        assert status["current_state"] == "blocked"
        assert status["history"][0]["blocked_reason"]

        # Incomplete override rejected (FR-008).
        incomplete = {
            "authorising_identity": "dev@datafoundry.local",
            "reason": "",
            "expiry": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
            "impact_assessment": "verified manually",
        }
        resp = client.post(f"/api/v1/datasets/{silver_id}/promotion/override", json=incomplete)
        assert resp.status_code == 422

        # Grant override -> promotion proceeds (US5-AC1).
        override = {
            "authorising_identity": "dev@datafoundry.local",
            "reason": "Known upstream incident; data verified manually",
            "expiry": (datetime.now(UTC) + timedelta(hours=24)).isoformat(),
            "impact_assessment": "3 downstream dashboards affected for <24h",
        }
        resp = client.post(f"/api/v1/datasets/{silver_id}/promotion/override", json=override)
        assert resp.status_code == 201, resp.text
        assert resp.json()["status"] == "active"

        # Re-run: override applies to the blocked run -> promotion proceeds.
        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["promotion_state"] == "silver_validated"

        # Override auditable (FR-008).
        from datafoundry.controlplane.db.models import AuditRecord

        with app.state.sessionmaker() as sess:
            actions = [r.action for r in sess.query(AuditRecord).all()]
        assert "promotion.overridden" in actions

    def test_expired_override_grants_no_permission(self, app, client):
        platform_id = _seed_platform(app)
        bronze_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        }
        silver_schema = {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        }
        bronze_id = _register_dataset(
            app, client, platform_id, "customer_bronze", "bronze", bronze_schema
        )
        silver_id = _register_dataset(
            app, client, platform_id, "customer_silver", "silver", silver_schema
        )
        transformation_id = _define_silver_transform(client)
        _define_failing_gate(app, silver_id)

        app.state.processing_gateway.seed_table(
            bronze_id,
            "bronze",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("email", pa.string()),
                ]
            ),
            [
                {"customer_id": 1, "email": "a@example.com"},
                {"customer_id": 1, "email": "a@example.com"},
            ],
        )
        app.state.quality_gateway.seed_table(
            silver_id,
            "silver",
            pa.schema(
                [
                    pa.field("customer_id", pa.int64()),
                    pa.field("email", pa.string()),
                ]
            ),
            [
                {"customer_id": 1, "email": "a@example.com"},
                {"customer_id": 1, "email": "a@example.com"},
            ],
        )

        # First run blocks.
        first = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        ).json()
        assert first["promotion_state"] == "blocked"

        # Grant an override that is ALREADY expired.
        expired = {
            "authorising_identity": "dev@datafoundry.local",
            "reason": "verified manually",
            "expiry": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
            "impact_assessment": "none",
        }
        resp = client.post(f"/api/v1/datasets/{silver_id}/promotion/override", json=expired)
        assert resp.status_code == 201, resp.text

        # Re-run: expired override grants no permission -> still blocked.
        response = client.post(
            f"/api/v1/transformations/{transformation_id}/run",
            json={"input_dataset_id": bronze_id, "environment": "production"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["promotion_state"] == "blocked"
