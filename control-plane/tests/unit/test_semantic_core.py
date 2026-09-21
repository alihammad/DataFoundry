"""T013: Unit tests for semantic foundational core.

Covers: semantic model schema conformance vs semantic-model-schema.md,
semantic test schema conformance vs semantic-test-schema.md, metric formula
compilation, semantic test registry resolution, and secret-scan on semantic
payloads.
"""

from __future__ import annotations

import uuid

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

    def test_registry_has_four_categories(self):
        # T025 registers the four categories.
        assert set(default_registry().categories()) == {
            "calculation",
            "reconciliation",
            "relationship",
            "filter",
        }


class TestSemanticAccess:
    """T031: access-policy enforcement (US3, FR-007)."""

    def test_row_filters_applied_to_query(self):
        gw = SimulatedSemanticGateway()
        result = compute_metric(
            gateway=gw,
            dataset="customers",
            layer="silver",
            measure_column="customer_id",
            aggregation="count",
            filter_spec=None,
            dimensions=[],
            definition_version=1,
            row_filters=["segment != 'vip'"],
        )
        # 3 customers; vip (Bob) excluded -> 2 (US3-AC3).
        assert result.value == 2

    def test_protected_column_masked_in_dimension_values(self):
        gw = SimulatedSemanticGateway()
        result = compute_metric(
            gateway=gw,
            dataset="customers",
            layer="silver",
            measure_column="customer_id",
            aggregation="count",
            filter_spec=None,
            dimensions=["email"],
            definition_version=1,
            protected_columns=["email"],
        )
        # email is protected -> masked in dimension values (US3-AC2, SC-005).
        assert result.dimension_values
        for row in result.dimension_values:
            assert row["email"] == "[REDACTED]"


class TestSemanticDiscovery:
    """T035: catalog discovery (FR-011, US4)."""

    def _seed_model(self, session, *, certification="draft"):
        from datafoundry.controlplane.db.models import (
            CertificationState,
            Metric,
            SemanticModel,
        )

        model = SemanticModel(
            domain="commerce",
            version=1,
            config_yaml="",
            config_hash="abc",
            certification_state=CertificationState(certification),
            created_by="dev@datafoundry.local",
        )
        session.add(model)
        session.flush()
        metric = Metric(
            model_id=model.id,
            name="revenue",
            business_definition="Sum of order amount",
            formula={"measure": "order_amount", "aggregation": "sum"},
            dimensions=["customer"],
            bound_datasets=["orders"],
            owner_identity="analytics@acme.com",
        )
        session.add(metric)
        session.flush()
        return model, metric

    def test_published_surfaces(self, session):
        from datafoundry.controlplane.semantic.discovery import search_business_terms

        self._seed_model(session, certification="published")
        items = search_business_terms(session, query="revenue")
        assert len(items) == 1
        assert items[0].name == "revenue"
        assert items[0].certification_state == "published"

    def test_draft_hidden_by_default(self, session):
        from datafoundry.controlplane.semantic.discovery import search_business_terms

        self._seed_model(session, certification="draft")
        items = search_business_terms(session, query="revenue")
        assert items == []

    def test_draft_included_when_requested(self, session):
        from datafoundry.controlplane.semantic.discovery import search_business_terms

        self._seed_model(session, certification="draft")
        items = search_business_terms(session, query="revenue", include_drafts=True)
        assert len(items) == 1
        assert items[0].certification_state == "draft"

    def test_match_on_business_definition(self, session):
        from datafoundry.controlplane.semantic.discovery import search_business_terms

        self._seed_model(session, certification="published")
        items = search_business_terms(session, query="order amount")
        assert len(items) == 1
        assert items[0].name == "revenue"


class TestSemanticConsumers:
    """T037: consumer registration + notification (FR-005, FR-010)."""

    def _seed_metric(self, session):
        from datafoundry.controlplane.db.models import Metric, SemanticModel

        model = SemanticModel(
            domain="commerce",
            version=1,
            config_yaml="",
            config_hash="abc",
            certification_state="draft",
            created_by="dev@datafoundry.local",
        )
        session.add(model)
        session.flush()
        metric = Metric(
            model_id=model.id,
            name="revenue",
            business_definition="Sum of order amount",
            formula={"measure": "order_amount", "aggregation": "sum"},
            dimensions=["customer"],
            bound_datasets=["orders"],
            owner_identity="analytics@acme.com",
        )
        session.add(metric)
        session.flush()
        return metric

    def test_register_and_list(self, session):
        from datafoundry.controlplane.semantic.consumers import (
            list_consumers,
            register_consumer,
        )

        metric = self._seed_metric(session)
        register_consumer(
            session,
            metric_id=metric.id,
            consumer_identity="bi-team@acme.com",
            consumption_path="bi",
        )
        consumers = list_consumers(session, metric_id=metric.id)
        assert len(consumers) == 1
        assert consumers[0].consumer_identity == "bi-team@acme.com"
        assert consumers[0].consumption_path == "bi"

    def test_register_duplicate_is_idempotent(self, session):
        from datafoundry.controlplane.semantic.consumers import (
            list_consumers,
            register_consumer,
        )

        metric = self._seed_metric(session)
        register_consumer(
            session,
            metric_id=metric.id,
            consumer_identity="bi-team@acme.com",
            consumption_path="bi",
        )
        register_consumer(
            session,
            metric_id=metric.id,
            consumer_identity="bi-team@acme.com",
            consumption_path="bi",
        )
        assert len(list_consumers(session, metric_id=metric.id)) == 1

    def test_invalid_consumption_path(self, session):
        from datafoundry.controlplane.semantic.consumers import (
            ConsumerRegistrationError,
            register_consumer,
        )

        metric = self._seed_metric(session)
        with pytest.raises(ConsumerRegistrationError):
            register_consumer(
                session,
                metric_id=metric.id,
                consumer_identity="x@acme.com",
                consumption_path="nope",
            )

    def test_notify_consumers(self, session):
        from datafoundry.controlplane.semantic.consumers import (
            notify_consumers,
            register_consumer,
        )

        metric = self._seed_metric(session)
        register_consumer(
            session,
            metric_id=metric.id,
            consumer_identity="bi-team@acme.com",
            consumption_path="bi",
        )
        notified = notify_consumers(
            session, metric_id=metric.id, message="breaking change (FR-005)"
        )
        assert notified == ["bi-team@acme.com"]


class TestSemanticDeprecation:
    """T038: metric deprecation (FR-010)."""

    def _seed_metrics(self, session):
        from datafoundry.controlplane.db.models import Metric, SemanticModel

        model = SemanticModel(
            domain="commerce",
            version=1,
            config_yaml="",
            config_hash="abc",
            certification_state="draft",
            created_by="dev@datafoundry.local",
        )
        session.add(model)
        session.flush()
        metric = Metric(
            model_id=model.id,
            name="revenue",
            business_definition="Sum of order amount",
            formula={"measure": "order_amount", "aggregation": "sum"},
            dimensions=["customer"],
            bound_datasets=["orders"],
            owner_identity="analytics@acme.com",
        )
        session.add(metric)
        session.flush()
        successor = Metric(
            model_id=model.id,
            name="revenue_v2",
            business_definition="Sum of order amount v2",
            formula={"measure": "order_amount", "aggregation": "sum"},
            dimensions=["customer"],
            bound_datasets=["orders"],
            owner_identity="analytics@acme.com",
        )
        session.add(successor)
        session.flush()
        return metric, successor

    def test_deprecate_with_successor(self, session):
        from datafoundry.controlplane.db.models import CertificationState, SemanticModel
        from datafoundry.controlplane.semantic.deprecation import deprecate_metric

        metric, successor = self._seed_metrics(session)
        result = deprecate_metric(
            session,
            metric_id=metric.id,
            successor_metric_id=successor.id,
            availability_period_days=30,
        )
        assert result.successor_metric_id == successor.id
        assert result.availability_period_days == 30
        model = session.get(SemanticModel, metric.model_id)
        assert model.certification_state == CertificationState.deprecated

    def test_deprecate_unknown_metric(self, session):
        from datafoundry.controlplane.semantic.deprecation import (
            DeprecationError,
            deprecate_metric,
        )

        with pytest.raises(DeprecationError):
            deprecate_metric(
                session,
                metric_id=uuid.uuid4(),
                successor_metric_id=None,
                availability_period_days=30,
            )

    def test_deprecate_unknown_successor(self, session):
        from datafoundry.controlplane.semantic.deprecation import (
            DeprecationError,
            deprecate_metric,
        )

        metric, _ = self._seed_metrics(session)
        with pytest.raises(DeprecationError):
            deprecate_metric(
                session,
                metric_id=metric.id,
                successor_metric_id=uuid.uuid4(),
                availability_period_days=30,
            )
