"""Per-run root module generator (T016, R-01, R-11, FR-012).

Renders ``terraform/workspaces/<run_id>/main.tf.json`` composing the enabled
capability modules in dependency order with the common input/output contract
(capability-catalog.md). Disabled capabilities produce NO module block; their
step is recorded ``skipped`` by the orchestrator (T030).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datafoundry.controlplane.capabilities.registry import (
    Capability,
    CapabilityRegistry,
    default_registry,
)
from datafoundry.controlplane.config.schema import PlatformConfig
from datafoundry.controlplane.providers.base import ProviderAdapter, StateBackendConfig


@dataclass(frozen=True)
class GeneratedModule:
    """One rendered module block (kept for step planning / audit)."""

    capability_key: str
    module_source: str
    deploy_step: int


class RootModuleGenerator:
    """Generates the per-run Terraform root module from a validated config."""

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        *,
        terraform_root: Path | None = None,
    ) -> None:
        self.registry = registry or default_registry
        self._terraform_root = terraform_root

    # -- public API -----------------------------------------------------------

    def enabled_capabilities(self, config: PlatformConfig) -> list[Capability]:
        """Resolved enabled capabilities in canonical deploy order (R-11)."""
        explicit = config.capabilities.explicitly_enabled()
        resolved = self.registry.resolve_enabled(explicit)
        return self.registry.deploy_order(resolved)

    def skipped_capabilities(self, config: PlatformConfig) -> list[str]:
        """Selectable capability keys that are disabled (recorded `skipped`)."""
        enabled = {c.key for c in self.enabled_capabilities(config)}
        return sorted(key for key in self.registry.selectable_keys() if key not in enabled)

    def render(
        self,
        config: PlatformConfig,
        adapter: ProviderAdapter,
        *,
        run_id: str,
        backend: StateBackendConfig | None = None,
        tags: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Build the main.tf.json document (in memory; ``write`` persists it)."""
        provider = config.platform.provider
        modules: dict[str, Any] = {}
        for capability in self.enabled_capabilities(config):
            modules[capability.key] = self._module_block(config, capability, provider)

        document: dict[str, Any] = {
            "terraform": {
                "required_version": ">= 1.9",
            },
            "variable": {
                "platform_name": {"type": "string"},
                "environment": {"type": "string"},
                "region": {"type": "string"},
                "tags": {"type": "map(string)"},
                "encryption_enforced": {"type": "bool"},
            },
            "module": modules,
            "output": self._outputs(config),
        }
        if backend is not None:
            document["terraform"]["backend"] = {backend.type: backend.config}
        # Bind common variables to concrete config values via a tfvars-style
        # locals block consumed by modules through var.* defaults set in write().
        document["locals"] = {
            "platform_name": config.platform.name,
            "environment": config.platform.environment,
            "region": config.platform.region,
            "tags": tags or self.default_tags(config),
            "encryption_enforced": True,
        }
        return document

    def write(
        self,
        config: PlatformConfig,
        adapter: ProviderAdapter,
        *,
        run_id: str,
        workdir: Path,
        backend: StateBackendConfig | None = None,
        tags: dict[str, str] | None = None,
    ) -> Path:
        """Render and persist ``main.tf.json`` (+ terraform.tfvars) to workdir."""
        document = self.render(config, adapter, run_id=run_id, backend=backend, tags=tags)
        workdir.mkdir(parents=True, exist_ok=True)
        main_path = workdir / "main.tf.json"
        main_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")

        # Variable values (kept out of the JSON structure for clarity).
        tfvars = {
            "platform_name": config.platform.name,
            "environment": config.platform.environment,
            "region": config.platform.region,
            "tags": tags or self.default_tags(config),
            "encryption_enforced": True,
        }
        (workdir / "terraform.tfvars.json").write_text(
            json.dumps(tfvars, indent=2, sort_keys=True) + "\n"
        )
        return main_path

    def default_tags(self, config: PlatformConfig) -> dict[str, str]:
        return {
            "platform": config.platform.name,
            "environment": config.platform.environment,
            "managed_by": "datafoundry",
        }

    # -- internals --------------------------------------------------------------

    def _module_block(
        self, config: PlatformConfig, capability: Capability, provider: str
    ) -> dict[str, Any]:
        # Relative source from terraform/workspaces/<run_id>/ to
        # terraform/{provider}/{module_dir}/.
        source = f"../../{provider}/{capability.module_dir or capability.key}"
        block: dict[str, Any] = {
            "source": source,
            # Common module inputs (capability-catalog.md).
            "platform_name": "${local.platform_name}",
            "environment": "${local.environment}",
            "region": "${local.region}",
            "tags": "${local.tags}",
            "encryption_enforced": "${local.encryption_enforced}",
        }
        # Wire cross-module references from dependency outputs.
        block.update(self._dependency_wiring(config, capability))
        return block

    def _dependency_wiring(self, config: PlatformConfig, capability: Capability) -> dict[str, Any]:
        """kms_key_ref comes from the secrets module output; network_ref from
        networking (common contract). Only wired when those deps are enabled
        (core capabilities always are)."""
        wiring: dict[str, Any] = {}
        enabled = {c.key for c in self.enabled_capabilities(config)}
        if "secrets" in enabled:
            wiring["kms_key_ref"] = "${module.secrets.kms_key_ref}"
        else:
            kms_ref = config.encryption.at_rest.kms_key_ref if config.encryption else ""
            wiring["kms_key_ref"] = kms_ref
        if "networking" in enabled:
            wiring["network_ref"] = "${module.networking.network_ref}"
        else:
            wiring["network_ref"] = ""
        return wiring

    def _outputs(self, config: PlatformConfig) -> dict[str, Any]:
        """Common outputs re-exported per capability (endpoint, resource_ids,
        health_target, iam_principal)."""
        outputs: dict[str, Any] = {}
        for capability in self.enabled_capabilities(config):
            key = capability.key
            outputs[f"{key}_endpoint"] = {"value": f"${{module.{key}.endpoint}}"}
            outputs[f"{key}_resource_ids"] = {"value": f"${{module.{key}.resource_ids}}"}
            outputs[f"{key}_health_target"] = {"value": f"${{module.{key}.health_target}}"}
            outputs[f"{key}_iam_principal"] = {"value": f"${{module.{key}.iam_principal}}"}
        return outputs
