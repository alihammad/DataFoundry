"""Region-capability matrix source (supports T012; generated form lands in T061).

Per deployment-api.md §3 and capability-catalog.md parity rule 2, a
capability is "supported on a provider/region" only when its module exists
(``terraform/{provider}/{key}/``) — the matrix is *generated from actual
module availability*, not hand-maintained. This class resolves availability
from disk (with an injectable override for tests) and applies known
managed-service region restrictions.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from datafoundry.controlplane.capabilities.registry import default_registry


class ModuleAvailabilityMatrix:
    """Which capabilities are supported in which regions for one provider."""

    def __init__(
        self,
        *,
        provider_id: str,
        regions: Iterable[str],
        terraform_root: Path | None = None,
        region_restrictions: dict[str, frozenset[str]] | None = None,
        available_capabilities: Iterable[str] | None = None,
    ) -> None:
        self.provider_id = provider_id
        self.regions = tuple(regions)
        self._terraform_root = terraform_root
        self._restrictions = region_restrictions or {}
        # Injectable override (tests / generated snapshot); None => probe disk.
        self._available_override = (
            frozenset(available_capabilities) if available_capabilities is not None else None
        )
        self._disk_cache: frozenset[str] | None = None

    # -- capability availability -------------------------------------------

    def available_capabilities(self) -> frozenset[str]:
        """Capability keys whose module directory exists for this provider."""
        if self._available_override is not None:
            return self._available_override
        if self._disk_cache is None:
            self._disk_cache = self._probe_disk()
        return self._disk_cache

    def _probe_disk(self) -> frozenset[str]:
        available: set[str] = set()
        for capability in default_registry.capabilities.values():
            if self._terraform_root is None:
                # No terraform tree resolvable (e.g. unit tests): assume the
                # full MVP catalog is available; restrictions still apply.
                available.add(capability.key)
                continue
            module_dir = (
                self._terraform_root / self.provider_id / (capability.module_dir or capability.key)
            )
            if module_dir.is_dir():
                available.add(capability.key)
        return frozenset(available)

    # -- queries -------------------------------------------------------------

    def supports(self, region: str, capability_key: str) -> bool:
        if region not in self.regions:
            return False
        if capability_key not in self.available_capabilities():
            return False
        allowed = self._restrictions.get(capability_key)
        return allowed is None or region in allowed

    def regions_for(self, capability_key: str) -> tuple[str, ...]:
        return tuple(r for r in self.regions if self.supports(r, capability_key))

    def capabilities_for(self, region: str) -> tuple[str, ...]:
        return tuple(
            key for key in sorted(self.available_capabilities()) if self.supports(region, key)
        )

    def as_dict(self) -> dict[str, list[str]]:
        """Serialisable matrix: region -> supported capability keys (§3 API)."""
        return {region: list(self.capabilities_for(region)) for region in self.regions}
