"""T013: Unit tests for semantic foundational core.

Covers: semantic model schema conformance vs semantic-model-schema.md,
semantic test schema conformance vs semantic-test-schema.md, metric formula
compilation, semantic test registry resolution, and secret-scan on semantic
payloads.
"""

from __future__ import annotations

import pytest
from datafoundry.controlplane.config.semantic_schema import (
    SemanticConfigError,
    validate_semantic_model,
    validate_semantic_tests,
)
from datafoundry.controlplane.semantic.compute.engine import (
    MetricCompilationError,
    compile_metric_query,
    compute_metric,
)
from datafoundry.controlplane.semantic.compute.gateway import SimulatedSemanticGateway
from datafoundry.controlplane.semantic.tests.registry import (
    UnknownSemanticTestCategoryError,
    default_registry,
    resolve_test,
)

VALID_MODEL = {
    "domain": "commerce",
    "metrics": [
        {
            "name": "revenue",
            "business_definition": "Sum of order amount",
            "formula": {"measure": "order_amount", "aggregation": "sum"},
            "dimensions": ["customer", "time"],
            "bound_datasets": ["orders"],
            "owner": "analytics@acme.com",
        }
    ],
    "dimensions": [
        {"name": "customer", "members": ["customer_id"], "protection_status": "internal"},
        {"name": "time", "members": ["order_date"], "protection_status": "public"},
    ],
    "measures": [
        {"name": "order_amount", "dataset": "orders", "column": "amount", "data_type": "numeric"}
    ],
    "relationships": [
        {
            "name": "orders_customer",
            "left_dataset": "orders",
            "right_dataset": "customers",
            "join_key": "customer_id",
            "join_type": "inner",
        }
    ],
}

VALID_TESTS = {
    "tests": [
        {
            "name": "revenue_calculation",
            "category": "calculation",
            "parameters": {"reference_data": "orders_ref", "expected_value": 525.0},
        },
        {
            "name": "orders_customer_relationship",
            "category": "relationship",
            "parameters": {"relationship": "orders_customer", "max_fanout": 1},
        },
    ]
}


class TestSemanticModelSchema:
    def test_valid(self):
        model = validate_semantic_model(VALID_MODEL)
        assert model.domain == "commerce"
        assert model.metrics[0].name == "revenue"

    def test_unknown_field_rejected(self):
        bad = dict(VALID_MODEL)
        bad["extra"] = "nope"
        with pytest.raises(SemanticConfigError):
            validate_semantic_model(bad)

    def test_duplicate_metric_name(self):
        bad = dict(VALID_MODEL)
        bad["metrics"] = [dict(VALID_MODEL["metrics"][0]), dict(VALID_MODEL["metrics"][0])]
        with pytest.raises(SemanticConfigError) as exc:
            validate_semantic_model(bad)
        assert any("unique" in e for e in exc.value.errors)

    def test_unknown_measure_reference(self):
        bad = dict(VALID_MODEL)
        bad["metrics"] = [dict(VALID_MODEL["metrics"][0])]
        bad["metrics"][0]["formula"] = {"measure": "nope", "aggregation": "sum"}
        with pytest.raises(SemanticConfigError) as exc:
            validate_semantic_model(bad)
        assert any("unknown measure" in e for e in exc.value.errors)

    def test_unknown_dimension_reference(self):
        bad = dict(VALID_MODEL)
        bad["metrics"] = [dict(VALID_MODEL["metrics"][0])]
        bad["metrics"][0]["dimensions"] = ["nope"]
        with pytest.raises(SemanticConfigError) as exc:
            validate_semantic_model(bad)
        assert any("unknown dimension" in e for e in exc.value.errors)

    def test_secret_scan_hit(self):
        bad = dict(VALID_MODEL)
        bad["metrics"] = [dict(VALID_MODEL["metrics"][0])]
        bad["metrics"][0]["business_definition"] = "AKIAIOSFODNN7EXAMPLE"
        with pytest.raises(SemanticConfigError) as exc:
            validate_semantic_model(bad)
        assert any("secret-scan" in e for e in exc.value.errors)


class TestSemanticTestSchema:
    def test_valid(self):
        model = validate_semantic_tests(VALID_TESTS)
        assert len(model.tests) == 2

    def test_unknown_field_rejected(self):
        bad = dict(VALID_TESTS)
        bad["extra"] = "nope"
        with pytest.raises(SemanticConfigError):
            validate_semantic_tests(bad)

    def test_duplicate_test_name(self):
        bad = dict(VALID_TESTS)
        bad["tests"] = [dict(VALID_TESTS["tests"][0]), dict(VALID_TESTS["tests"][0])]
        with pytest.raises(SemanticConfigError) as exc:
            validate_semantic_tests(bad)
        assert any("unique" in e for e in exc.value.errors)

    def test_calculation_requires_expected_value(self):
        bad = dict(VALID_TESTS)
        bad["tests"] = [
            {
                "name": "revenue_calculation",
                "category": "calculation",
                "parameters": {"reference_data": "orders_ref"},
            }
        ]
        with pytest.raises(SemanticConfigError) as exc:
            validate_semantic_tests(bad)
        assert any("expected_value" in e for e in exc.value.errors)

    def test_relationship_requires_max_fanout(self):
        bad = dict(VALID_TESTS)
        bad["tests"] = [
            {
                "name": "rel",
                "category": "relationship",
                "parameters": {"relationship": "orders_customer"},
            }
        ]
        with pytest.raises(SemanticConfigError) as exc:
            validate_semantic_tests(bad)
        assert any("max_fanout" in e for e in exc.value.errors)


class TestMetricCompilation:
    def test_compile_simple_sum(self):
        sql = compile_metric_query(
            measure_column="amount",
            aggregation="sum",
            dataset="orders",
            filter_spec=None,
            dimensions=[],
        )
        assert "SUM(amount)" in sql
        assert "FROM orders" in sql

    def test_compile_with_filter_and_dimensions(self):
        sql = compile_metric_query(
            measure_column="amount",
            aggregation="sum",
            dataset="orders",
            filter_spec={"order_status": "COMPLETED"},
            dimensions=["region"],
        )
        assert "region" in sql
        assert "order_status = 'COMPLETED'" in sql
        assert "GROUP BY region" in sql

    def test_unsupported_aggregation(self):
        with pytest.raises(MetricCompilationError):
            compile_metric_query(
                measure_column="amount",
                aggregation="median",
                dataset="orders",
                filter_spec=None,
                dimensions=[],
            )

    def test_compute_metric_over_gateway(self):
        gw = SimulatedSemanticGateway()
        result = compute_metric(
            gateway=gw,
            dataset="orders",
            layer="gold",
            measure_column="amount",
            aggregation="sum",
            filter_spec=None,
            dimensions=[],
            definition_version=1,
        )
        # 100 + 250 + 75 + 50 + 50 = 525
        assert result.value == 525.0
        assert result.definition_version == 1
        assert result.quality_state == "passed"

    def test_compute_metric_unknown_dataset(self):
        gw = SimulatedSemanticGateway()
        with pytest.raises(MetricCompilationError):
            compute_metric(
                gateway=gw,
                dataset="nope",
                layer="gold",
                measure_column="amount",
                aggregation="sum",
                filter_spec=None,
                dimensions=[],
                definition_version=1,
            )


class TestSemanticTestRegistry:
    def test_unknown_category_raises(self):
        with pytest.raises(UnknownSemanticTestCategoryError):
            resolve_test("nope")

    def test_registry_has_no_implementations_yet(self):
        # T025 registers concrete categories; until then none resolve.
        assert default_registry().categories() == ()
