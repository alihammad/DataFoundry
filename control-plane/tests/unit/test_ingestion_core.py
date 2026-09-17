"""Unit tests for feature 002 foundational core (T014).

Covers: ingestion config schema conformance, connector registry resolution,
contract change classification, high-watermark advance-on-commit semantics,
and secret-scan on ingestion payloads.
"""

from __future__ import annotations

import uuid

import pytest
from datafoundry.controlplane.config.ingestion_schema import (
    IngestionConfigError,
    validate_ingestion_config,
)
from datafoundry.controlplane.db.models import (
    DataSource,
    IngestionConfig,
    IngestionMode,
    IngestionPipeline,
    IngestionRun,
    RunTrigger,
    SourceType,
    TargetZone,
)
from datafoundry.controlplane.ingestion.connectors.base import Connector
from datafoundry.controlplane.ingestion.connectors.registry import (
    clear,
    register,
    registered_types,
    resolve,
)
from datafoundry.controlplane.ingestion.contract import classify_change
from datafoundry.controlplane.ingestion.gateway import (
    SimTable,
    SimulatedLandingGateway,
    SimulatedSourceGateway,
)
from datafoundry.controlplane.ingestion.security import (
    reject_secrets,
    scan_ingestion_payload,
)
from datafoundry.controlplane.ingestion.validation import (
    reconcile_record_count,
    validate_contract_compat,
    validate_file,
)

VALID_CONFIG = {
    "apiVersion": "datafoundry/v1",
    "kind": "IngestionConfig",
    "metadata": {"name": "crm-to-bronze", "source": "crm-prod"},
    "source": {
        "type": "postgres",
        "objects": [
            {"name": "customer", "mode": "incremental", "cursor_column": "updated_at"},
            {"name": "orders", "mode": "full"},
        ],
    },
    "schedule": "every 15 minutes",
    "target": {"zone": "bronze"},
    "validation": {"reconciliation_tolerance": 0, "contract_mode": "enforce"},
}


# -- T007: ingestion config schema --------------------------------------------


class TestIngestionConfigSchema:
    def test_valid_config(self):
        model = validate_ingestion_config(VALID_CONFIG)
        assert model.metadata.name == "crm-to-bronze"
        assert model.source.type == "postgres"

    def test_unknown_field_rejected(self):
        bad = {**VALID_CONFIG, "extra": "nope"}
        with pytest.raises(IngestionConfigError):
            validate_ingestion_config(bad)

    def test_incremental_without_cursor_rejected(self):
        bad = {
            **VALID_CONFIG,
            "source": {
                "type": "postgres",
                "objects": [{"name": "customer", "mode": "incremental"}],
            },
        }
        with pytest.raises(IngestionConfigError) as exc:
            validate_ingestion_config(bad)
        assert "cursor_column" in str(exc.value)

    def test_object_storage_requires_file_pattern(self):
        bad = {
            **VALID_CONFIG,
            "source": {"type": "object_storage"},
        }
        with pytest.raises(IngestionConfigError) as exc:
            validate_ingestion_config(bad)
        assert "filePattern" in str(exc.value)

    def test_invalid_schedule_rejected(self):
        bad = {**VALID_CONFIG, "schedule": "not-a-schedule"}
        with pytest.raises(IngestionConfigError) as exc:
            validate_ingestion_config(bad)
        assert "schedule" in str(exc.value)

    def test_secret_scan_rejects_credentials(self):
        bad = {
            **VALID_CONFIG,
            "source": {
                "type": "postgres",
                "objects": [{"name": "customer", "mode": "full"}],
            },
            "metadata": {"name": "crm-to-bronze", "source": "crm-prod"},
        }
        # Inject a credential value into the config.
        bad["source"]["password"] = "AKIAIOSFODNN7EXAMPLE"
        with pytest.raises(IngestionConfigError) as exc:
            validate_ingestion_config(bad)
        assert "secret-scan" in str(exc.value)


# -- T008: connector registry --------------------------------------------------


class _FakeConnector(Connector):
    source_type = "fake"

    def discover_schema(self, config_ref):
        return {"tables": []}

    def test_connection(self, config_ref):
        return {"ok": True}

    def extract(self, config_ref, *, object_name, cursor_column=None, watermark=None):
        return []


class TestConnectorRegistry:
    def test_register_and_resolve(self):
        clear()
        register(_FakeConnector)
        assert resolve("fake") is _FakeConnector
        assert "fake" in registered_types()

    def test_resolve_unknown_raises(self):
        clear()
        with pytest.raises(KeyError):
            resolve("nope")


# -- T011: contract change classification --------------------------------------


class TestClassifyChange:
    def test_type_change_is_breaking(self):
        result = classify_change(
            column="customer_id", change="type_change", old_type="integer", new_type="string"
        )
        assert result["classification"] == "breaking"

    def test_dropped_column_is_breaking(self):
        result = classify_change(column="email", change="dropped_column")
        assert result["classification"] == "breaking"

    def test_added_column_is_non_breaking(self):
        result = classify_change(column="new_col", change="added_column")
        assert result["classification"] == "non_breaking"

    def test_nullability_tightened_is_warning(self):
        result = classify_change(column="name", change="nullability_tightened")
        assert result["classification"] == "warning"


# -- T010: validation ----------------------------------------------------------


class TestValidation:
    def test_validate_file_valid_parquet(self):
        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.table({"a": [1, 2, 3]})
        buf = pa.BufferOutputStream()
        pq.write_table(table, buf)
        content = buf.getvalue().to_pybytes()
        result = validate_file(content=content, file_name="data.parquet")
        assert result["ok"] is True

    def test_validate_file_corrupt(self):
        result = validate_file(content=b"not-a-parquet", file_name="data.parquet")
        assert result["ok"] is False
        assert result["failed_check"] == "format"

    def test_validate_file_checksum_mismatch(self):
        result = validate_file(content=b"hello", file_name="data.csv", declared_checksum="deadbeef")
        assert result["ok"] is False
        assert result["failed_check"] == "checksum"

    def test_contract_compat_breaking_type_change(self):
        expected = {"customer_id": {"type": "integer", "nullable": False}}
        observed = {"customer_id": {"type": "string", "nullable": False}}
        violations = validate_contract_compat(expected, observed)
        assert any(v["classification"] == "breaking" for v in violations)

    def test_reconcile_failure(self):
        result = reconcile_record_count(source_count=1_000_000, ingested_count=999_870)
        assert result["ok"] is False
        assert result["difference"] == 130

    def test_reconcile_within_tolerance(self):
        result = reconcile_record_count(source_count=100, ingested_count=99, tolerance=1)
        assert result["ok"] is True


# -- T012: secret-scan wiring --------------------------------------------------


class TestSecretScanWiring:
    def test_scan_ingestion_payload_detects_secret(self):
        findings = scan_ingestion_payload({"password": "AKIAIOSFODNN7EXAMPLE"})
        assert findings

    def test_reject_secrets_raises(self):
        with pytest.raises(ValueError):
            reject_secrets({"secretRef": "AKIAIOSFODNN7EXAMPLE"}, what="config_ref")

    def test_reject_secrets_allows_secret_ref(self):
        # A secretRef pointer (not a value) must pass.
        reject_secrets({"secretRef": "secrets/crm-prod"}, what="config_ref")


# -- T009: high-watermark advance-on-commit ------------------------------------


class TestHighWatermark:
    def _seed(self):
        gateway = SimulatedSourceGateway()
        gateway.seed_database("src-1")
        gateway.add_table(
            "src-1",
            SimTable(
                name="customer",
                columns=[
                    {"name": "id", "type": "integer", "nullable": False},
                    {"name": "updated_at", "type": "string", "nullable": False},
                ],
            ),
            rows=[
                {"id": 1, "updated_at": "2026-09-01"},
                {"id": 2, "updated_at": "2026-09-02"},
            ],
        )
        return gateway

    def _seed_gateway_for_source(self, gateway, source_id):
        """Re-key the simulated gateway to the DB source id."""
        gateway.seed_database(str(source_id))
        gateway.add_table(
            str(source_id),
            SimTable(
                name="customer",
                columns=[
                    {"name": "id", "type": "integer", "nullable": False},
                    {"name": "updated_at", "type": "string", "nullable": False},
                ],
            ),
            rows=[
                {"id": 1, "updated_at": "2026-09-01"},
                {"id": 2, "updated_at": "2026-09-02"},
            ],
        )

    def _seed_platform(self, session):
        from datafoundry.controlplane.db.models import (
            EnvironmentType,
            Platform,
            Provider,
        )

        platform = Platform(
            name="test-platform",
            provider=Provider.aws,
            cloud_scope_id="scope-1",
            region="us-east-1",
            environment_type=EnvironmentType.test,
            owner_identity="dev@datafoundry.local",
        )
        session.add(platform)
        session.flush()
        return platform.id

    def test_watermark_advances_on_validated_commit(self, session_factory):
        from datafoundry.controlplane.db.models import (
            DataSource,
            IngestionConfig,
            IngestionMode,
            IngestionPipeline,
            IngestionRun,
            IngestionRunStatus,
            RunTrigger,
            SourceType,
            TargetZone,
        )
        from datafoundry.controlplane.ingestion.engine import run_ingestion

        gateway = self._seed()
        landing = SimulatedLandingGateway()
        with session_factory() as session:
            platform_id = self._seed_platform(session)
            source = DataSource(
                platform_id=platform_id,
                name="crm-prod",
                type=SourceType.postgres,
                config_ref={"host": "db", "secretRef": "secrets/crm"},
                owner_identity="dev@datafoundry.local",
            )
            session.add(source)
            session.flush()
            self._seed_gateway_for_source(gateway, source.id)
            config = IngestionConfig(
                source_id=source.id,
                version=1,
                config_yaml="apiVersion: datafoundry/v1",
                config_hash="a" * 64,
                source_type=SourceType.postgres,
                selected_objects={
                    "objects": [
                        {"name": "customer", "mode": "incremental", "cursor_column": "updated_at"}
                    ]
                },
                ingestion_mode=IngestionMode.incremental,
                target_zone=TargetZone.bronze,
                created_by="dev@datafoundry.local",
            )
            session.add(config)
            session.flush()
            pipeline = IngestionPipeline(
                config_id=config.id,
                source_id=source.id,
                name="crm-pipeline",
                owner_identity="dev@datafoundry.local",
            )
            session.add(pipeline)
            session.flush()
            run = IngestionRun(pipeline_id=pipeline.id, trigger=RunTrigger.manual)
            session.add(run)
            session.commit()
            run_id = run.id
            pipeline_id = pipeline.id

            run_ingestion(session, gateway=gateway, run_id=run_id, landing=landing)
            session.commit()

            refreshed = session.get(IngestionRun, run_id)
            assert refreshed.status == IngestionRunStatus.succeeded
            pipe = session.get(IngestionPipeline, pipeline_id)
            assert pipe.high_watermarks["customer"] == "2026-09-02"
            assert landing.committed_paths()

    def test_watermark_not_advanced_on_failed_batch(self, session_factory):
        from datafoundry.controlplane.db.models import (
            DataSource,
            IngestionConfig,
            IngestionMode,
            IngestionPipeline,
            IngestionRun,
            RunTrigger,
            SourceType,
            TargetZone,
        )
        from datafoundry.controlplane.ingestion.engine import run_ingestion

        gateway = self._seed()
        landing = SimulatedLandingGateway()
        with session_factory() as session:
            platform_id = self._seed_platform(session)
            source = DataSource(
                platform_id=platform_id,
                name="crm-prod",
                type=SourceType.postgres,
                config_ref={"host": "db", "secretRef": "secrets/crm"},
                owner_identity="dev@datafoundry.local",
            )
            session.add(source)
            session.flush()
            self._seed_gateway_for_source(gateway, source.id)
            config = IngestionConfig(
                source_id=source.id,
                version=1,
                config_yaml="apiVersion: datafoundry/v1",
                config_hash="a" * 64,
                source_type=SourceType.postgres,
                selected_objects={
                    "objects": [
                        {"name": "customer", "mode": "incremental", "cursor_column": "updated_at"}
                    ]
                },
                ingestion_mode=IngestionMode.incremental,
                target_zone=TargetZone.bronze,
                created_by="dev@datafoundry.local",
            )
            session.add(config)
            session.flush()
            pipeline = IngestionPipeline(
                config_id=config.id,
                source_id=source.id,
                name="crm-pipeline",
                owner_identity="dev@datafoundry.local",
            )
            session.add(pipeline)
            session.flush()
            run = IngestionRun(pipeline_id=pipeline.id, trigger=RunTrigger.manual)
            session.add(run)
            session.commit()
            run_id = run.id
            pipeline_id = pipeline.id

            # Point the config at a table that does not exist so extract fails.
            config.selected_objects = {
                "objects": [
                    {"name": "missing_table", "mode": "incremental", "cursor_column": "updated_at"}
                ]
            }
            run_ingestion(session, gateway=gateway, run_id=run_id, landing=landing)
            session.commit()

            pipe = session.get(IngestionPipeline, pipeline_id)
            # Watermark must NOT advance on a failed batch.
            assert "missing_table" not in pipe.high_watermarks


# -- T036/FR-020: ingestion alerting + FR-009/US3-AC4 reconciliation ----------


class TestIngestionAlerts:
    def _seed_platform(self, session):
        from datafoundry.controlplane.db.models import (
            EnvironmentType,
            Platform,
            Provider,
        )

        platform = Platform(
            name="alert-platform",
            provider=Provider.aws,
            cloud_scope_id="scope-1",
            region="us-east-1",
            environment_type=EnvironmentType.test,
            owner_identity="dev@datafoundry.local",
        )
        session.add(platform)
        session.flush()
        return platform

    def test_alert_run_failure_redacts_secrets(self, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord
        from datafoundry.controlplane.ingestion.alerts import alert_run_failure

        with session_factory() as sess:
            platform = self._seed_platform(sess)
            alert_run_failure(
                sess,
                actor="dev@datafoundry.local",
                platform_id=platform.id,
                pipeline_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                source_id=uuid.uuid4(),
                object_name="customer",
                reason="connection refused; password=supersecretvalue123456",
            )
            sess.commit()
        with session_factory() as sess:
            record = sess.query(AuditRecord).one()
            assert record.action == "ingestion.alert.run_failure"
            assert record.payload["object_name"] == "customer"
            assert "supersecretvalue123456" not in str(record.payload["reason"])

    def test_alert_breaking_change_persists_violations(self, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord
        from datafoundry.controlplane.ingestion.alerts import alert_breaking_change

        with session_factory() as sess:
            platform = self._seed_platform(sess)
            alert_breaking_change(
                sess,
                actor="dev@datafoundry.local",
                platform_id=platform.id,
                pipeline_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                source_id=uuid.uuid4(),
                object_name="orders",
                violations=[
                    {"classification": "breaking", "column": "id", "change": "int->string"}
                ],
            )
            sess.commit()
        with session_factory() as sess:
            record = sess.query(AuditRecord).one()
            assert record.action == "ingestion.alert.breaking_change"
            assert record.payload["violations"][0]["classification"] == "breaking"

    def test_alert_reconciliation_failure(self, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord
        from datafoundry.controlplane.ingestion.alerts import alert_reconciliation_failure

        with session_factory() as sess:
            platform = self._seed_platform(sess)
            alert_reconciliation_failure(
                sess,
                actor="dev@datafoundry.local",
                platform_id=platform.id,
                pipeline_id=uuid.uuid4(),
                run_id=uuid.uuid4(),
                source_id=uuid.uuid4(),
                object_name="customer",
                source_count=1_000_000,
                ingested_count=999_870,
                difference=130,
                tolerance=0,
            )
            sess.commit()
        with session_factory() as sess:
            record = sess.query(AuditRecord).one()
            assert record.action == "ingestion.alert.reconciliation_failure"
            assert record.payload["difference"] == 130


class TestReconciliationWiring:
    """Engine-level record-count reconciliation (FR-009, US3-AC4)."""

    def test_reconciliation_failure_blocks_promotion(self, session_factory):
        from datafoundry.controlplane.db.models import (
            BatchStatus,
            EnvironmentType,
            IngestionBatch,
            IngestionRunStatus,
            Platform,
            Provider,
        )

        # Source has 2 rows but the gateway reports 1_000_000 via count_rows.
        gateway = SimulatedSourceGateway()
        gateway.seed_database("src-1")
        gateway.add_table(
            "src-1",
            SimTable(
                name="customer",
                columns=[
                    {"name": "id", "type": "integer", "nullable": False},
                    {"name": "updated_at", "type": "string", "nullable": False},
                ],
            ),
            rows=[
                {"id": 1, "updated_at": "2026-09-01"},
                {"id": 2, "updated_at": "2026-09-02"},
            ],
        )
        # Override count_rows to simulate a mismatch.
        gateway.count_rows = lambda source_id, *, object_name: 1_000_000

        landing = SimulatedLandingGateway()
        with session_factory() as session:
            platform = Platform(
                name="test-platform",
                provider=Provider.aws,
                cloud_scope_id="scope-1",
                region="us-east-1",
                environment_type=EnvironmentType.test,
                owner_identity="dev@datafoundry.local",
            )
            session.add(platform)
            session.flush()
            source = DataSource(
                platform_id=platform.id,
                name="crm-prod",
                type=SourceType.postgres,
                config_ref={"host": "db", "secretRef": "secrets/crm"},
                owner_identity="dev@datafoundry.local",
            )
            session.add(source)
            session.flush()
            gateway.seed_database(str(source.id))
            gateway.add_table(
                str(source.id),
                SimTable(
                    name="customer",
                    columns=[
                        {"name": "id", "type": "integer", "nullable": False},
                        {"name": "updated_at", "type": "string", "nullable": False},
                    ],
                ),
                rows=[
                    {"id": 1, "updated_at": "2026-09-01"},
                    {"id": 2, "updated_at": "2026-09-02"},
                ],
            )
            config = IngestionConfig(
                source_id=source.id,
                version=1,
                config_yaml="apiVersion: datafoundry/v1",
                config_hash="a" * 64,
                source_type=SourceType.postgres,
                selected_objects={"objects": [{"name": "customer", "mode": "full"}]},
                ingestion_mode=IngestionMode.full,
                target_zone=TargetZone.bronze,
                created_by="dev@datafoundry.local",
            )
            session.add(config)
            session.flush()
            pipeline = IngestionPipeline(
                config_id=config.id,
                source_id=source.id,
                name="crm-pipeline",
                owner_identity="dev@datafoundry.local",
            )
            session.add(pipeline)
            session.flush()
            run = IngestionRun(pipeline_id=pipeline.id, trigger=RunTrigger.manual)
            session.add(run)
            session.commit()
            run_id = run.id

            from datafoundry.controlplane.ingestion.engine import run_ingestion

            run_ingestion(session, gateway=gateway, run_id=run_id, landing=landing)
            session.commit()

            batch = session.query(IngestionBatch).one()
            assert batch.status == BatchStatus.ingested
            assert batch.metadata_json["status"] == "ingested"
            assert batch.metadata_json["reconciliation"]["ok"] is False
            refreshed = session.get(IngestionRun, run_id)
            assert refreshed.status == IngestionRunStatus.succeeded
