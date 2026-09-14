"""Generated region-capability matrix (T061).

Contract rule (capability-catalog.md parity rule 2, deployment-api.md §3):
the matrix is GENERATED from actual module availability on disk — never
hand-maintained. A capability is "supported on a provider" iff its module
directory ``terraform/{provider}/{module_dir}/`` exists (and, for managed
services with regional availability limits, the region is in the provider's
restriction set).

``generate_matrix`` snapshots the current terraform/ tree into a JSON
document consumed by:
- validation (config/validation.py rule 4 via provider adapters),
- ``GET /providers/{provider}/regions`` (deployment-api.md §3),
- the capability-parity checklist (SC-003).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from datafoundry.controlplane.capabilities.registry import (
    CapabilityRegistry,
    default_registry,
)
from datafoundry.controlplane.providers.base import ProviderRegistry, default_providers


@dataclass(frozen=True)
class MatrixDocument:
    """Serialisable region-capability matrix for one or more providers."""

    generated_from: str
    providers: dict[str, dict[str, list[str]]]  # provider -> region -> capabilities

    def as_dict(self) -> dict[str, Any]:
        return {
            "generated_from": self.generated_from,
            "providers": self.providers,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=True) + "\n"


def available_modules(
    provider_id: str,
    terraform_root: Path,
    registry: CapabilityRegistry | None = None,
) -> dict[str, bool]:
    """capability key -> module directory exists on disk."""
    registry = registry or default_registry
    availability: dict[str, bool] = {}
    for capability in registry.capabilities.values():
        module_dir = terraform_root / provider_id / (capability.module_dir or capability.key)
        availability[capability.key] = module_dir.is_dir()
    return availability


def generate_matrix(
    terraform_root: Path,
    *,
    providers: ProviderRegistry | None = None,
    registry: CapabilityRegistry | None = None,
) -> MatrixDocument:
    """Generate the matrix from actual module availability per provider."""
    providers = providers or default_providers
    registry = registry or default_registry
    document: dict[str, dict[str, list[str]]] = {}
    for provider_id in providers.provider_ids():
        adapter = providers.get(provider_id)
        per_region: dict[str, list[str]] = {}
        for region in adapter.regions():
            per_region[region] = [
                key for key in sorted(registry.keys()) if adapter.region_supports(region, key)
            ]
        document[provider_id] = per_region
    return MatrixDocument(generated_from=str(terraform_root), providers=document)


def write_matrix_snapshot(
    terraform_root: Path,
    output_path: Path,
    *,
    providers: ProviderRegistry | None = None,
    registry: CapabilityRegistry | None = None,
) -> Path:
    """Write the generated matrix snapshot (CI artifact / parity checklist)."""
    matrix = generate_matrix(terraform_root, providers=providers, registry=registry)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(matrix.to_json())
    return output_path


def parity_report(
    terraform_root: Path,
    *,
    providers: ProviderRegistry | None = None,
    registry: CapabilityRegistry | None = None,
) -> dict[str, Any]:
    """Capability-parity data (SC-003): which capabilities each provider
    delivers, and gaps between providers."""
    providers = providers or default_providers
    registry = registry or default_registry
    per_provider = {
        provider_id: sorted(
            key
            for key, exists in available_modules(provider_id, terraform_root, registry).items()
            if exists
        )
        for provider_id in providers.provider_ids()
    }
    all_keys = set(registry.keys())
    gaps = {provider_id: sorted(all_keys - set(keys)) for provider_id, keys in per_provider.items()}
    return {"providers": per_provider, "gaps": gaps}


if __name__ == "__main__":  # pragma: no cover - manual generator entry point
    import sys

    root = Path(sys.argv[1] if len(sys.argv) > 1 else Path.cwd() / "terraform")
    out = Path(sys.argv[2] if len(sys.argv) > 2 else root / "region-matrix.json")
    write_matrix_snapshot(root, out)
    print(f"wrote {out}")
