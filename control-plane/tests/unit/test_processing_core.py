"""T013: Unit tests for processing foundational core.

Covers: transformation config schema conformance, transformation registry
resolution, promotion state machine transitions (gate pass/block), and
secret-scan on processing payloads.
"""

from __future__ import annotations

import pytest
from datafoundry.controlplane.config.transformation_schema import (
    TransformationConfigError,
    validate_transformation_definition,
)
from datafoundry.controlplane.db.models import PromotionState
from datafoundry.controlplane.processing.promotion import (
    can_promote_to_layer,
    next_state,
    transition,
)
from datafoundry.controlplane.processing.security import (
    scan_processing_payload,
)
from datafoundry.controlplane.processing.transformations.registry import (
    build_registry,
    resolve_transformation,
)

VALID_SILVER = {
    "name": "customer_silver_transform",
    "source_layer": "bronze",
    "target_layer": "silver",
    "dedup_keys": ["customer_id"],
    "reconciliation_tolerance": 0.5,
    "logic": {
        "type": "silver",
        "cleansing": [{"column": "email", "op": "trim"}],
        "standardisation": [{"column": "country", "op": "upper"}],
        "schema_enforcement": {
            "customer_id": {"type": "integer", "nullable": False},
            "email": {"type": "string", "nullable": False},
        },
    },
}

VALID_GOLD = {
    "name": "customer_360_gold",
    "source_layer": "silver",
    "target_layer": "gold",
    "reconciliation_tolerance": 0.5,
    "logic": {
        "type": "gold",
        "aggregation": {
            "group_by": ["customer_id"],
            "measures": [{"name": "total_amount", "op": "sum", "column": "amount"}],
        },
        "reconciliation": {
            "sql": "SELECT SUM(amount) AS total FROM silver_orders",
            "tolerance_pct": 0.5,
        },
    },
}


# -- T007: transformation config schema ----------------------------------------


class TestTransformationSchema:
    def test_valid_silver(self):
        model = validate_transformation_definition(VALID_SILVER)
        assert model.source_layer == "bronze"
        assert model.target_layer == "silver"
        assert model.logic.type == "silver"

    def test_valid_gold(self):
        model = validate_transformation_definition(VALID_GOLD)
        assert model.source_layer == "silver"
        assert model.target_layer == "gold"
        assert model.logic.type == "gold"

    def test_unknown_field_rejected(self):
        bad = dict(VALID_SILVER)
        bad["extra"] = "nope"
        with pytest.raises(TransformationConfigError):
            validate_transformation_definition(bad)

    def test_layer_must_be_one_below(self):
        bad = dict(VALID_SILVER)
        bad["source_layer"] = "gold"  # gold -> silver is not one below
        with pytest.raises(TransformationConfigError):
            validate_transformation_definition(bad)

    def test_bad_name_rejected(self):
        bad = dict(VALID_SILVER)
        bad["name"] = "Bad Name!"
        with pytest.raises(TransformationConfigError):
            validate_transformation_definition(bad)

    def test_secret_scan_hit(self):
        bad = dict(VALID_SILVER)
        bad["logic"]["cleansing"] = [{"column": "password", "op": "trim"}]
        bad["logic"]["schema_enforcement"] = {"password": {"type": "string", "nullable": False}}
        # Inject a secret value into a field.
        bad["logic"]["schema_enforcement"]["password"]["type"] = "AKIAIOSFODNN7EXAMPLE"
        with pytest.raises(TransformationConfigError) as exc:
            validate_transformation_definition(bad)
        assert any("secret-scan" in e for e in exc.value.errors)


# -- T008: transformation registry ---------------------------------------------


class TestTransformationRegistry:
    def test_resolve_silver(self):
        build_registry()
        impl = resolve_transformation("silver")
        assert impl.logic_type == "silver"

    def test_resolve_gold(self):
        build_registry()
        impl = resolve_transformation("gold")
        assert impl.logic_type == "gold"

    def test_unknown_type_raises(self):
        with pytest.raises(KeyError):
            resolve_transformation("nope")


# -- T009: promotion state machine ---------------------------------------------


class TestPromotionStateMachine:
    def test_next_state_chain(self):
        assert next_state(PromotionState.ingested) == PromotionState.ingestion_validated
        assert next_state(PromotionState.bronze_validated) == PromotionState.silver
        assert next_state(PromotionState.consumable) is None

    def test_can_promote_to_layer(self):
        assert can_promote_to_layer(PromotionState.ingestion_validated, "bronze")
        assert can_promote_to_layer(PromotionState.bronze_validated, "silver")
        assert can_promote_to_layer(PromotionState.silver_validated, "gold")
        assert not can_promote_to_layer(PromotionState.bronze, "silver")

    def test_gate_pass_promotes(self):
        state = transition(
            PromotionState.bronze_validated,
            gate_passed=True,
            target_layer="silver",
        )
        assert state == PromotionState.silver_validated

    def test_gate_fail_blocks(self):
        state = transition(
            PromotionState.bronze_validated,
            gate_passed=False,
            target_layer="silver",
            blocked_reason="gate failed",
        )
        assert state == PromotionState.blocked

    def test_entry_layer_gate_pass(self):
        state = transition(None, gate_passed=True, target_layer="bronze")
        assert state == PromotionState.bronze


# -- T011: secret-scan on processing payloads ----------------------------------


class TestProcessingSecretScan:
    def test_detects_secret(self):
        findings = scan_processing_payload({"logic_definition": "AKIAIOSFODNN7EXAMPLE"})
        assert findings

    def test_clean_payload_no_findings(self):
        findings = scan_processing_payload({"logic_definition": {"type": "silver"}})
        assert not findings
