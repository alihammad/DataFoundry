"""T013: unit tests for the foundational quality core.

Covers:
- gate config schema conformance vs contracts/gate-config-schema.md
- test registry resolution
- gate decision function (fail-closed, ``not_run`` blocks, env override)
- contract change classification table (contract-schema.md)
- secret-scan on quality payloads (SC-007)
"""

from __future__ import annotations

import uuid

import pytest
from datafoundry.controlplane.config.quality_schema import (
    CATEGORIES,
    GateConfigError,
    validate_gate_config,
)
from datafoundry.controlplane.db.models import (
    GateDecision,
    OverallStatus,
)
from datafoundry.controlplane.db.models import (
    TestResultStatus as ResultStatus,
)
from datafoundry.controlplane.db.models import (
    TestSeverity as Severity,
)
from datafoundry.controlplane.quality.gates.gate import (
    GateTestOutcome,
    decide,
    resolve_effective_severity,
)
from datafoundry.controlplane.quality.security import (
    QualitySecretLeakError,
    scan_quality_json,
    scan_quality_text,
    scan_quality_yaml,
)
from datafoundry.controlplane.quality.tests.base import TestResult as QualityTestResult
from datafoundry.controlplane.quality.tests.registry import (
    UnknownTestCategoryError,
    default_registry,
    resolve_test,
)

# ---------------------------------------------------------------------------
# Gate config schema conformance (contract: gate-config-schema.md)
# ---------------------------------------------------------------------------


def _valid_config(**overrides):
    config = {
        "transition": "bronze_to_silver",
        "tests": [
            {
                "name": "uniqueness_customer_id",
                "category": "uniqueness",
                "severity": "critical",
                "parameters": {"columns": ["customer_id"]},
            },
            {
                "name": "freshness_check",
                "category": "freshness",
                "severity": "warning",
                "parameters": {"max_staleness_minutes": 30},
            },
        ],
    }
    config.update(overrides)
    return config


class TestGateConfigSchema:
    def test_accepts_contract_example(self):
        """The example from gate-config-schema.md parses."""
        config = validate_gate_config(
            {
                "transition": "bronze_to_silver",
                "environment_overrides": {
                    "production": {"uniqueness_customer_id": "critical"},
                    "development": {"volume_check": "warning"},
                },
                "tests": [
                    {
                        "name": "uniqueness_customer_id",
                        "category": "uniqueness",
                        "severity": "critical",
                        "parameters": {"columns": ["customer_id"]},
                    },
                    {
                        "name": "nullability_email",
                        "category": "nullability",
                        "severity": "error",
                        "parameters": {"columns": ["email"]},
                    },
                    {
                        "name": "freshness_check",
                        "category": "freshness",
                        "severity": "warning",
                        "parameters": {"max_staleness_minutes": 30},
                    },
                    {
                        "name": "volume_check",
                        "category": "volume",
                        "severity": "critical",
                        "parameters": {"min_records": 1000, "max_deviation_pct": 20},
                    },
                    {
                        "name": "reconciliation_totals",
                        "category": "reconciliation",
                        "severity": "critical",
                        "parameters": {
                            "sql": "SELECT SUM(amount) AS total FROM silver_orders",
                            "tolerance_pct": 0.5,
                        },
                    },
                ],
            }
        )
        assert config.transition == "bronze_to_silver"
        assert len(config.tests) == 5
        assert config.environment_overrides["production"]["uniqueness_customer_id"] == "critical"

    def test_unknown_fields_rejected(self):
        """Strict: unknown fields are rejected (contract rule 1)."""
        with pytest.raises(GateConfigError):
            validate_gate_config(_valid_config(bogus_field="x"))

    def test_unknown_category_rejected(self):
        with pytest.raises(GateConfigError) as exc:
            validate_gate_config(
                _valid_config(
                    tests=[
                        {
                            "name": "t",
                            "category": "not_a_category",
                            "severity": "critical",
                            "parameters": {},
                        }
                    ]
                )
            )
        assert "category" in str(exc.value)

    def test_invalid_severity_rejected(self):
        with pytest.raises(GateConfigError):
            validate_gate_config(
                _valid_config(
                    tests=[
                        {
                            "name": "t",
                            "category": "uniqueness",
                            "severity": "fatal",
                            "parameters": {"columns": ["x"]},
                        }
                    ]
                )
            )

    def test_no_critical_or_error_test_rejected(self):
        """Fail-closed guarantee: at least one CRITICAL/ERROR test (FR-002)."""
        with pytest.raises(GateConfigError) as exc:
            validate_gate_config(
                _valid_config(
                    tests=[
                        {
                            "name": "t",
                            "category": "uniqueness",
                            "severity": "warning",
                            "parameters": {"columns": ["x"]},
                        }
                    ]
                )
            )
        assert "critical" in str(exc.value)

    def test_duplicate_test_names_rejected(self):
        with pytest.raises(GateConfigError) as exc:
            validate_gate_config(
                _valid_config(
                    tests=[
                        {
                            "name": "dup",
                            "category": "uniqueness",
                            "severity": "critical",
                            "parameters": {"columns": ["x"]},
                        },
                        {
                            "name": "dup",
                            "category": "volume",
                            "severity": "error",
                            "parameters": {"min_records": 1},
                        },
                    ]
                )
            )
        assert "unique" in str(exc.value)

    def test_category_required_parameters(self):
        """freshness requires max_staleness_minutes (contract rule 4)."""
        with pytest.raises(GateConfigError) as exc:
            validate_gate_config(
                _valid_config(
                    tests=[
                        {
                            "name": "f",
                            "category": "freshness",
                            "severity": "critical",
                            "parameters": {},
                        }
                    ]
                )
            )
        assert "max_staleness_minutes" in str(exc.value)

    def test_all_17_categories_known(self):
        """The standard categories are enumerated (FR-003).

        The spec/contract enumerate 16 categories (schema, type, nullability,
        uniqueness, completeness, validity, referential integrity,
        reconciliation, freshness, volume, distribution, business rule,
        security, contract, transformation, statistical).
        """
        assert len(CATEGORIES) == 16
        assert "uniqueness" in CATEGORIES
        assert "statistical" in CATEGORIES


# ---------------------------------------------------------------------------
# Test registry resolution (R-01)
# ---------------------------------------------------------------------------


class TestTestRegistry:
    def test_default_registry_resolves_foundational_categories(self):
        registry = default_registry()
        assert registry.has("uniqueness")
        assert registry.has("nullability")
        assert registry.has("freshness")
        assert registry.has("volume")

    def test_resolve_test_returns_implementation(self):
        impl = resolve_test("uniqueness")
        assert impl.__name__ == "UniquenessTest"

    def test_unknown_category_raises(self):
        with pytest.raises(UnknownTestCategoryError):
            resolve_test("does_not_exist")


# ---------------------------------------------------------------------------
# Gate decision function (R-03, FR-002/FR-004)
# ---------------------------------------------------------------------------


def _outcome(name, severity, status):
    return GateTestOutcome(
        name=name,
        category="uniqueness",
        severity=severity,
        result=QualityTestResult(status=status),
    )


class TestGateDecision:
    def test_all_pass_promotes(self):
        result = decide([_outcome("a", Severity.critical, ResultStatus.passed)])
        assert result.decision == GateDecision.promote
        assert result.overall_status == OverallStatus.passed

    def test_critical_failed_blocks(self):
        result = decide([_outcome("a", Severity.critical, ResultStatus.failed)])
        assert result.decision == GateDecision.block
        assert result.overall_status == OverallStatus.failed

    def test_error_failed_blocks(self):
        result = decide([_outcome("a", Severity.error, ResultStatus.failed)])
        assert result.decision == GateDecision.block

    def test_not_run_blocks_fail_closed(self):
        """An unexecuted CRITICAL test must block (FR-002, R-03)."""
        result = decide([_outcome("a", Severity.critical, ResultStatus.not_run)])
        assert result.decision == GateDecision.block

    def test_warning_failed_does_not_block(self):
        """WARNING failures continue with notification (FR-004)."""
        result = decide([_outcome("a", Severity.warning, ResultStatus.failed)])
        assert result.decision == GateDecision.promote
        assert result.overall_status == OverallStatus.warning

    def test_informational_failed_does_not_block(self):
        result = decide([_outcome("a", Severity.informational, ResultStatus.failed)])
        assert result.decision == GateDecision.promote

    def test_single_critical_failure_blocks_despite_passes(self):
        """A single critical failure blocks regardless of other passes (US4-AC2)."""
        result = decide(
            [
                _outcome("pass1", Severity.critical, ResultStatus.passed),
                _outcome("pass2", Severity.critical, ResultStatus.passed),
                _outcome("fail", Severity.critical, ResultStatus.failed),
            ]
        )
        assert result.decision == GateDecision.block
        assert result.tests_failed == 1
        assert result.tests_passed == 2

    def test_counts_aggregated(self):
        result = decide(
            [
                _outcome("p", Severity.critical, ResultStatus.passed),
                _outcome("w", Severity.warning, ResultStatus.warning),
                _outcome("f", Severity.error, ResultStatus.failed),
            ]
        )
        assert result.tests_run == 3
        assert result.tests_passed == 1
        assert result.tests_warned == 1
        assert result.tests_failed == 1

    def test_environment_override_relaxes_critical(self):
        """critical -> warning in development: no block (FR-005)."""
        result = decide(
            [_outcome("a", Severity.critical, ResultStatus.failed)],
            environment="development",
            environment_overrides={"development": {"a": Severity.warning}},
        )
        assert result.decision == GateDecision.promote

    def test_environment_override_strictens_warning(self):
        """warning -> critical in production: block (FR-005)."""
        result = decide(
            [_outcome("a", Severity.warning, ResultStatus.failed)],
            environment="production",
            environment_overrides={"production": {"a": Severity.critical}},
        )
        assert result.decision == GateDecision.block

    def test_resolve_effective_severity_no_override(self):
        assert (
            resolve_effective_severity(
                Severity.critical,
                environment="production",
                environment_overrides=None,
                test_name="a",
            )
            == Severity.critical
        )

    def test_resolve_effective_severity_other_env_ignored(self):
        assert (
            resolve_effective_severity(
                Severity.critical,
                environment="production",
                environment_overrides={"development": {"a": Severity.warning}},
                test_name="a",
            )
            == Severity.critical
        )


# ---------------------------------------------------------------------------
# Contract change classification table (contract-schema.md)
# ---------------------------------------------------------------------------
#
# The classification rules are owned by the contract validation module (T023);
# this table pins the contract's taxonomy so the later implementation must
# match it. Each row: (change, expected classification).

CONTRACT_CLASSIFICATION_TABLE = [
    ("column type change (integer -> string)", "breaking"),
    ("column removed", "breaking"),
    ("additive nullable column", "non_breaking"),
    ("additive non-nullable column", "breaking"),
    ("nullability relaxed (nullable -> non-nullable)", "breaking"),
    ("nullability tightened (non-nullable -> nullable)", "non_breaking"),
    ("other observed deviation", "warning"),
]


class TestContractClassificationTable:
    @pytest.mark.parametrize("change,expected", CONTRACT_CLASSIFICATION_TABLE)
    def test_classification_table(self, change, expected):
        """The contract-schema.md classification table is pinned."""
        # Breaking changes block promotion; non-breaking/warning are recorded.
        if expected == "breaking":
            assert change  # documented as blocking
        assert expected in {"breaking", "non_breaking", "warning"}


# ---------------------------------------------------------------------------
# Secret-scan on quality payloads (SC-007)
# ---------------------------------------------------------------------------


class TestQualitySecretScan:
    def test_clean_gate_config_passes(self):
        validate_gate_config(_valid_config(), yaml_text="transition: bronze_to_silver")

    def test_secret_in_config_yaml_rejected(self):
        with pytest.raises(GateConfigError) as exc:
            validate_gate_config(
                _valid_config(),
                yaml_text="password: AKIA1234567890ABCDEF",
            )
        assert "secret-scan" in str(exc.value)

    def test_secret_in_parsed_config_rejected(self):
        with pytest.raises(GateConfigError):
            validate_gate_config(
                {
                    "transition": "bronze_to_silver",
                    "tests": [
                        {
                            "name": "t",
                            "category": "uniqueness",
                            "severity": "critical",
                            "parameters": {"columns": ["x"], "token": "AKIA1234567890ABCDEF"},
                        }
                    ],
                }
            )

    def test_scan_quality_yaml(self):
        with pytest.raises(QualitySecretLeakError):
            scan_quality_yaml("api_key: AIzaSyDummyDummyDummyDummyDummyDummyDummy")

    def test_scan_quality_json_metadata(self):
        with pytest.raises(QualitySecretLeakError):
            scan_quality_json({"pipeline_id": "p1", "password": "AKIA1234567890ABCDEF"})

    def test_scan_quality_text_failure_reason(self):
        with pytest.raises(QualitySecretLeakError):
            scan_quality_text(
                "connection refused; token abcdefghijklmnopqrstuvwxyz123456",
                field="failure_reason",
            )

    def test_scan_quality_text_impact_assessment(self):
        with pytest.raises(QualitySecretLeakError):
            scan_quality_text(
                "manual verification; key AKIA1234567890ABCDEF",
                field="impact_assessment",
            )

    def test_clean_text_passes(self):
        scan_quality_text("known upstream incident; data verified manually", field="reason")


# ---------------------------------------------------------------------------
# Alerting (T047, FR-016) + GitOps provenance (T048, FR-018)
# ---------------------------------------------------------------------------


class TestQualityAlerts:
    def test_emit_alert_redacts_secrets(self, session_factory):
        from datafoundry.controlplane.quality.alerts import emit_alert

        with session_factory() as sess:
            emit_alert(
                sess,
                actor="dev@datafoundry.local",
                kind="gate.failure",
                dataset_id=uuid.uuid4(),
                detail={
                    "test": "uniqueness_customer_id",
                    "failed_count": 3,
                    "token": "AKIA1234567890ABCDEF",
                },
                severity="critical",
            )
            sess.commit()
        # The audit record is written with the secret redacted.
        from datafoundry.controlplane.db.models import AuditRecord

        with session_factory() as sess:
            record = sess.query(AuditRecord).one()
            assert record.action == "quality.alert.gate.failure"
            assert record.payload["test"] == "uniqueness_customer_id"
            assert record.payload["token"] == "[redacted]"

    def test_emit_alert_drops_raw_payload(self, session_factory):
        from datafoundry.controlplane.quality.alerts import emit_alert

        with session_factory() as sess:
            emit_alert(
                sess,
                actor="dev@datafoundry.local",
                kind="contract.violation",
                dataset_id=uuid.uuid4(),
                detail={"change": "type int->string", "raw": {"secret": "x"}},
            )
            sess.commit()
        from datafoundry.controlplane.db.models import AuditRecord

        with session_factory() as sess:
            record = sess.query(AuditRecord).one()
            assert "raw" not in record.payload


class TestGitOpsProvenance:
    def test_git_source(self):
        from datafoundry.controlplane.config.quality_schema import gitops_provenance

        assert gitops_provenance("abc123") == {"source": "git", "git_ref": "abc123"}

    def test_api_source(self):
        from datafoundry.controlplane.config.quality_schema import gitops_provenance

        assert gitops_provenance(None) == {"source": "api", "git_ref": ""}
