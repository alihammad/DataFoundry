"""T022: unit tests for the foundational core.

Covers:
- PlatformConfig schema conformance vs contracts/platform-config-schema.md
- secret-scan detection / false positives
- capability registry dependency closure + implicit database enablement
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from datafoundry.controlplane.capabilities.registry import (
    build_registry,
    default_registry,
)
from datafoundry.controlplane.config.schema import PlatformConfig
from datafoundry.controlplane.config.secret_scan import (
    has_secrets,
    redact_text,
    scan_value,
    scan_yaml_text,
    shannon_entropy,
)
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLES = REPO_ROOT / "platform-configs" / "examples"


def _minimal_config(**overrides):
    config = {
        "apiVersion": "datafoundry/v1",
        "kind": "PlatformConfig",
        "platform": {
            "name": "customer-analytics",
            "provider": "gcp",
            "region": "australia-southeast1",
            "environment": "development",
        },
        "capabilities": {
            "storage_zones": {"enabled": True},
            "networking": {"enabled": True},
            "iam": {"enabled": True},
            "secrets": {"enabled": True},
        },
    }
    _deep_update(config, overrides)
    return config


def _deep_update(base: dict, updates: dict) -> dict:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


# ---------------------------------------------------------------------------
# Schema conformance (contract: platform-config-schema.md)
# ---------------------------------------------------------------------------


class TestPlatformConfigSchema:
    def test_accepts_contract_example(self):
        """The full example from the contract document parses."""
        raw = yaml.safe_load((EXAMPLES / "dev-aws-localstack.yaml").read_text())
        config = PlatformConfig.model_validate(raw)
        assert config.platform.name == "customer-analytics-dev"
        assert config.platform.provider == "aws"
        assert config.storage.table_format == "iceberg"
        assert config.storage.zones.bronze.retention_days == -1
        assert config.encryption is not None
        assert config.encryption.in_transit.min_tls == "1.2"

    def test_all_valid_examples_parse(self):
        for path in sorted(EXAMPLES.glob("*.yaml")):
            if path.name == "bad-config.yaml":
                continue  # semantically invalid, covered below
            raw = yaml.safe_load(path.read_text())
            # Ingestion configs (feature 002) live in the same examples dir but
            # use a different kind; they are validated by the ingestion schema.
            if raw.get("kind") != "PlatformConfig":
                continue
            PlatformConfig.model_validate(raw)

    def test_bad_config_is_structurally_valid(self):
        """bad-config.yaml fails *semantic* rules (region matrix, dependency
        closure, production approval) — not structure. It must parse."""
        raw = yaml.safe_load((EXAMPLES / "bad-config.yaml").read_text())
        config = PlatformConfig.model_validate(raw)
        assert config.platform.region == "us-west-99"
        assert config.is_production
        assert config.approval is None  # FR-010 violation caught in T028

    def test_unknown_fields_rejected_strict(self):
        with pytest.raises(ValidationError) as exc_info:
            PlatformConfig.model_validate(_minimal_config(bogusField="x"))
        assert "bogusField" in str(exc_info.value)

    def test_unknown_nested_fields_rejected(self):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(_minimal_config(platform={"extra": "nope"}))

    def test_wrong_api_version_rejected(self):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(_minimal_config(apiVersion="datafoundry/v2"))

    def test_wrong_kind_rejected(self):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(_minimal_config(kind="SomethingElse"))

    def test_missing_required_sections(self):
        raw = _minimal_config()
        del raw["platform"]
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(raw)

    @pytest.mark.parametrize(
        "name",
        ["ab", "Customer", "1abc", "-abc", "a" * 64, "has_underscore", "has space"],
    )
    def test_invalid_platform_names(self, name):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(_minimal_config(platform={"name": name}))

    @pytest.mark.parametrize("name", ["datafoundry", "system"])
    def test_reserved_names_rejected(self, name):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(_minimal_config(platform={"name": name}))

    def test_valid_name_boundaries(self):
        PlatformConfig.model_validate(_minimal_config(platform={"name": "abc"}))
        PlatformConfig.model_validate(_minimal_config(platform={"name": "a" * 63}))

    def test_unknown_provider_rejected(self):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(_minimal_config(platform={"provider": "azure"}))

    def test_unknown_environment_rejected(self):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(_minimal_config(platform={"environment": "staging"}))

    def test_core_capability_cannot_be_disabled(self):
        for core in ("networking", "secrets", "storage_zones", "iam"):
            with pytest.raises(ValidationError):
                PlatformConfig.model_validate(
                    _minimal_config(capabilities={core: {"enabled": False}})
                )

    def test_bronze_retention_must_be_immutable(self):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(
                _minimal_config(storage={"zones": {"bronze": {"retention_days": 30}}})
            )

    def test_invalid_retention_values(self):
        for days in (0, -5):
            with pytest.raises(ValidationError):
                PlatformConfig.model_validate(
                    _minimal_config(storage={"zones": {"silver": {"retention_days": days}}})
                )

    def test_isolation_variants_parse(self):
        # cidr presence rules are semantic (T028), not structural.
        PlatformConfig.model_validate(_minimal_config(networking={"isolation": "private"}))
        PlatformConfig.model_validate(
            _minimal_config(networking={"isolation": "private", "cidr": "10.0.0.0/16"})
        )
        # public parses at schema level (forbidden in prod by T028)
        PlatformConfig.model_validate(_minimal_config(networking={"isolation": "public"}))

    def test_invalid_cidr_rejected(self):
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(
                _minimal_config(networking={"isolation": "private", "cidr": "10.0.0.0/99"})
            )

    def test_defaults_applied(self):
        config = PlatformConfig.model_validate(_minimal_config())
        assert config.storage.table_format == "iceberg"
        assert config.networking.isolation == "private"
        assert config.secrets.backend == "cloud_native"
        assert config.observability.tracing == "opentelemetry"
        assert config.observability.log_retention_days == 90
        assert config.encryption is None
        assert config.approval is None
        assert not config.is_production

    def test_strict_types_no_coercion(self):
        # strict mode: string "true" must not coerce to bool
        with pytest.raises(ValidationError):
            PlatformConfig.model_validate(
                _minimal_config(capabilities={"catalog": {"enabled": "true"}})
            )

    def test_explicitly_enabled_set(self):
        config = PlatformConfig.model_validate(
            _minimal_config(
                capabilities={
                    "compute": {"enabled": True, "size": "medium"},
                    "catalog": {"enabled": True},
                    "quality": {"enabled": False},
                }
            )
        )
        assert config.capabilities.explicitly_enabled() == {
            "networking",
            "secrets",
            "storage_zones",
            "iam",
            "compute",
            "catalog",
        }


# ---------------------------------------------------------------------------
# Secret scan (contract rule 7, SC-006)
# ---------------------------------------------------------------------------


class TestSecretScan:
    def test_detects_aws_access_key_id(self):
        findings = scan_value({"key": "AKIAIOSFODNN7EXAMPLE"})
        assert any(f.kind == "aws_access_key_id" for f in findings)

    def test_detects_gcp_api_key(self):
        findings = scan_value({"k": "AIza" + "A" * 35})
        assert any(f.kind == "gcp_api_key" for f in findings)

    def test_detects_pem_block(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n-----END RSA PRIVATE KEY-----"
        findings = scan_value({"cert": pem})
        assert any(f.kind == "private_key_pem" for f in findings)

    def test_detects_password_assignment(self):
        findings = scan_value({"note": "password: hunter2supersecretvalue"})
        assert findings

    def test_detects_high_entropy_string(self):
        token = "Xk9#mQ2$vL7@pR4!nB8%wZ3&cJ6*yT1"
        assert shannon_entropy(token) >= 4.0
        findings = scan_value({"value": token})
        assert any(f.kind == "high_entropy_string" for f in findings)

    def test_no_false_positive_on_normal_config(self):
        raw = yaml.safe_load((EXAMPLES / "dev-aws-localstack.yaml").read_text())
        assert scan_value(raw) == []

    def test_no_false_positive_on_hashes_and_refs(self):
        payload = {
            "config_hash": "a" * 16 + "0123456789abcdef" * 3,
            "git_ref": "9f8e7d6c5b4a39281706f5e4d3c2b1a098765432",
            "kms_key_ref": "platform-cmk",
        }
        assert scan_value(payload) == []

    def test_no_false_positive_on_prose(self):
        assert scan_value({"message": "Region us-west1 does not support orchestration"}) == []

    def test_scan_nested_structures(self):
        findings = scan_value({"a": {"b": [{"c": "AKIAIOSFODNN7EXAMPLE"}]}})
        assert findings[0].path == "$.a.b[0].c"

    def test_scan_yaml_text(self):
        text = "secrets:\n  token: AKIAIOSFODNN7EXAMPLE\n"
        assert scan_yaml_text(text)

    def test_has_secrets_helper(self):
        assert has_secrets("AKIAIOSFODNN7EXAMPLE")
        assert not has_secrets("just a normal sentence")

    def test_redact_text(self):
        redacted = redact_text("key AKIAIOSFODNN7EXAMPLE here")
        assert "AKIAIOSFODNN7EXAMPLE" not in redacted
        assert "[REDACTED]" in redacted


# ---------------------------------------------------------------------------
# Capability registry (capability-catalog.md)
# ---------------------------------------------------------------------------


class TestCapabilityRegistry:
    def test_mvp_keys_present(self):
        expected = {
            "networking",
            "secrets",
            "storage_zones",
            "iam",
            "compute",
            "database",
            "catalog",
            "orchestration",
            "ingestion",
            "quality",
            "semantic_layer",
            "monitoring",
        }
        assert set(default_registry.keys()) == expected

    def test_core_not_selectable(self):
        assert set(default_registry.core_keys()) == {
            "networking",
            "secrets",
            "storage_zones",
            "iam",
        }

    def test_module_path_pattern(self):
        cap = default_registry.get("storage_zones")
        assert cap.module_path("aws") == "terraform/aws/storage/"
        assert default_registry.get("semantic_layer").module_path("gcp") == (
            "terraform/gcp/semantic/"
        )
        assert default_registry.get("catalog").module_path("gcp") == ("terraform/gcp/catalog/")

    def test_transitive_closure(self):
        closure = default_registry.transitive_closure({"semantic_layer"})
        assert closure == {
            "semantic_layer",
            "catalog",
            "storage_zones",
            "database",
            "secrets",
            "iam",
            "networking",
        }

    def test_implicit_database_auto_enabled_by_catalog(self):
        resolved = default_registry.resolve_enabled(
            {"networking", "secrets", "storage_zones", "iam", "catalog"}
        )
        assert "database" in resolved

    def test_implicit_database_auto_enabled_by_orchestration(self):
        resolved = default_registry.resolve_enabled(
            {"networking", "secrets", "storage_zones", "iam", "compute", "orchestration"}
        )
        assert "database" in resolved

    def test_database_not_enabled_for_core_only(self):
        resolved = default_registry.resolve_enabled(
            {"networking", "secrets", "storage_zones", "iam"}
        )
        assert "database" not in resolved

    def test_explicit_database_honored(self):
        resolved = default_registry.resolve_enabled(
            {"networking", "secrets", "storage_zones", "iam", "database"}
        )
        assert "database" in resolved

    def test_missing_dependencies_reported(self):
        missing = default_registry.missing_dependencies({"semantic_layer"})
        assert ("semantic_layer", "catalog") in missing

    def test_deploy_order_sorted_by_step(self):
        resolved = default_registry.resolve_enabled(
            {
                "networking",
                "secrets",
                "storage_zones",
                "iam",
                "compute",
                "catalog",
                "orchestration",
                "ingestion",
                "monitoring",
            }
        )
        order = [c.key for c in default_registry.deploy_order(resolved)]
        assert order.index("networking") < order.index("secrets")
        assert order.index("secrets") < order.index("storage_zones")
        assert order.index("storage_zones") < order.index("catalog")
        assert order.index("catalog") < order.index("orchestration")
        assert order.index("orchestration") < order.index("ingestion")
        assert order.index("ingestion") < order.index("monitoring")

    def test_unknown_capability_raises(self):
        with pytest.raises(KeyError):
            default_registry.get("nonexistent")
        with pytest.raises(KeyError):
            default_registry.transitive_closure({"nonexistent"})

    def test_cycle_detection(self):
        from datafoundry.controlplane.capabilities.registry import Capability

        with pytest.raises(ValueError, match="cycle"):
            build_registry(
                (
                    Capability(
                        key="a",
                        display_name="A",
                        selectable=True,
                        depends_on=("b",),
                        health_check="x",
                        deploy_step=1,
                    ),
                    Capability(
                        key="b",
                        display_name="B",
                        selectable=True,
                        depends_on=("a",),
                        health_check="x",
                        deploy_step=2,
                    ),
                )
            )

    def test_duplicate_key_rejected(self):
        from datafoundry.controlplane.capabilities.registry import Capability

        cap = Capability(
            key="a", display_name="A", selectable=True, health_check="x", deploy_step=1
        )
        with pytest.raises(ValueError, match="duplicate"):
            build_registry((cap, cap))
