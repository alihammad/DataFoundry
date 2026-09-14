"""Capability registry (T011).

Code-defined catalog per contracts/capability-catalog.md: MVP keys,
``selectable`` flag, ``depends_on`` graph (incl. implicit ``database``
auto-enable), ``module_path`` pattern ``terraform/{provider}/{key}/``,
``health_check`` runner id, and ``deploy_step`` position in the canonical
step order (R-11).

Adding a capability = adding a ``Capability`` entry here + provider modules;
no core code changes (FR-015 spirit applies to providers, FR-012 to keys).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final


@dataclass(frozen=True)
class Capability:
    """One logical capability in the registry."""

    key: str
    display_name: str
    selectable: bool
    depends_on: tuple[str, ...] = ()
    health_check: str = ""
    deploy_step: int = 0
    #: Directory name under terraform/{provider}/ — differs from key where the
    #: contract maps e.g. storage_zones -> storage, semantic_layer -> semantic.
    module_dir: str | None = None
    #: When true, this capability is auto-enabled if any dependent capability
    #: is enabled (implicit dependency; surfaced in validation).
    implicit: bool = False

    @property
    def module_path_pattern(self) -> str:
        return f"terraform/{{provider}}/{self.module_dir or self.key}/"

    def module_path(self, provider: str) -> str:
        return self.module_path_pattern.format(provider=provider)


@dataclass(frozen=True)
class CapabilityRegistry:
    """Immutable registry of MVP capabilities."""

    capabilities: dict[str, Capability] = field(default_factory=dict)

    # -- lookups ---------------------------------------------------------

    def get(self, key: str) -> Capability:
        try:
            return self.capabilities[key]
        except KeyError:
            raise KeyError(f"unknown capability '{key}'") from None

    def keys(self) -> tuple[str, ...]:
        return tuple(self.capabilities)

    def selectable_keys(self) -> tuple[str, ...]:
        return tuple(k for k, c in self.capabilities.items() if c.selectable)

    def core_keys(self) -> tuple[str, ...]:
        return tuple(k for k, c in self.capabilities.items() if not c.selectable)

    # -- dependency graph -------------------------------------------------

    def transitive_closure(self, enabled: set[str]) -> set[str]:
        """All capabilities required by ``enabled`` (transitive depends_on)."""
        closure: set[str] = set()
        stack = list(enabled)
        while stack:
            key = stack.pop()
            if key in closure:
                continue
            closure.add(key)
            capability = self.capabilities.get(key)
            if capability is None:
                raise KeyError(f"unknown capability '{key}'")
            stack.extend(capability.depends_on)
        return closure

    def resolve_enabled(self, explicitly_enabled: set[str]) -> set[str]:
        """Full enabled set: explicit keys + transitive deps + implicit
        auto-enable (``database`` when catalog/orchestration/ingestion/quality/
        semantic_layer is enabled)."""
        enabled = self.transitive_closure(explicitly_enabled)
        changed = True
        while changed:
            changed = False
            for capability in self.capabilities.values():
                if not capability.implicit or capability.key in enabled:
                    continue
                if any(dep in enabled for dep in self._implicit_triggers(capability.key)):
                    enabled.add(capability.key)
                    changed = True
        return enabled

    def _implicit_triggers(self, key: str) -> set[str]:
        """Capabilities whose presence auto-enables the implicit ``key``."""
        return {other.key for other in self.capabilities.values() if key in other.depends_on}

    def missing_dependencies(self, enabled: set[str]) -> list[tuple[str, str]]:
        """(capability, missing_dep) pairs where an enabled capability's
        dependency is not enabled — validation rule 5 input."""
        missing: list[tuple[str, str]] = []
        for key in sorted(enabled):
            capability = self.capabilities.get(key)
            if capability is None:
                continue
            for dep in capability.depends_on:
                if dep not in enabled:
                    missing.append((key, dep))
        return missing

    def deploy_order(self, enabled: set[str]) -> list[Capability]:
        """Enabled capabilities sorted by canonical deploy step (R-11)."""
        return sorted(
            (self.capabilities[k] for k in enabled if k in self.capabilities),
            key=lambda c: (c.deploy_step, c.key),
        )


def _cap(
    key: str,
    display: str,
    *,
    selectable: bool,
    depends_on: tuple[str, ...] = (),
    health_check: str,
    deploy_step: int,
    module_dir: str | None = None,
    implicit: bool = False,
) -> Capability:
    return Capability(
        key=key,
        display_name=display,
        selectable=selectable,
        depends_on=depends_on,
        health_check=health_check,
        deploy_step=deploy_step,
        module_dir=module_dir,
        implicit=implicit,
    )


#: MVP registry exactly per contracts/capability-catalog.md.
MVP_CAPABILITIES: Final[tuple[Capability, ...]] = (
    _cap(
        "networking",
        "Network Isolation",
        selectable=False,
        health_check="dns-resolve",
        deploy_step=5,
    ),
    _cap(
        "secrets",
        "Secrets & KMS",
        selectable=False,
        depends_on=("networking",),
        health_check="kms-decrypt-probe",
        deploy_step=6,
    ),
    _cap(
        "storage_zones",
        "Object Storage + Zones",
        selectable=False,
        depends_on=("secrets",),
        health_check="zone-head",
        deploy_step=7,
        module_dir="storage",
    ),
    _cap(
        "iam",
        "Identity & Access",
        selectable=False,
        depends_on=("networking",),
        health_check="token-mint",
        deploy_step=8,
    ),
    _cap(
        "compute",
        "Compute",
        selectable=True,
        depends_on=("iam",),
        health_check="instance-ready",
        deploy_step=9,
    ),
    # database: auto-enabled when any of catalog/orchestration/ingestion/
    # quality/semantic_layer is enabled (implicit dependency).
    _cap(
        "database",
        "Platform Database",
        selectable=True,
        depends_on=("iam", "secrets"),
        health_check="pg-ping",
        deploy_step=10,
        implicit=True,
    ),
    _cap(
        "catalog",
        "Metadata Catalog",
        selectable=True,
        depends_on=("storage_zones", "database"),
        health_check="http-health",
        deploy_step=11,
    ),
    _cap(
        "orchestration",
        "Orchestration",
        selectable=True,
        depends_on=("compute", "database"),
        health_check="airflow-health",
        deploy_step=12,
    ),
    # Steps 13/13b/13c/14 per capability-catalog.md, scaled x10 so they stay
    # ints while preserving the canonical order: ingestion=130, quality=131,
    # semantic_layer=132, monitoring=140.
    _cap(
        "ingestion",
        "Ingestion Service",
        selectable=True,
        depends_on=("storage_zones", "catalog"),
        health_check="endpoint-responds",
        deploy_step=130,
    ),
    _cap(
        "quality",
        "Data Quality Gates",
        selectable=True,
        depends_on=("catalog",),
        health_check="runner-heartbeat",
        deploy_step=131,
    ),
    _cap(
        "semantic_layer",
        "Semantic Layer",
        selectable=True,
        depends_on=("catalog",),
        health_check="endpoint-responds",
        deploy_step=132,
        module_dir="semantic",
    ),
    _cap(
        "monitoring",
        "Monitoring & Observability",
        selectable=True,
        depends_on=("networking", "iam"),
        health_check="synthetic-datapoint",
        deploy_step=140,
    ),
)


def build_registry(capabilities: tuple[Capability, ...] = MVP_CAPABILITIES) -> CapabilityRegistry:
    registry: dict[str, Capability] = {}
    for capability in capabilities:
        if capability.key in registry:
            raise ValueError(f"duplicate capability key '{capability.key}'")
        registry[capability.key] = capability
    # Validate the dependency graph references known keys and is acyclic.
    for capability in capabilities:
        for dep in capability.depends_on:
            if dep not in registry:
                raise ValueError(
                    f"capability '{capability.key}' depends on unknown capability '{dep}'"
                )
    _assert_acyclic(registry)
    return CapabilityRegistry(capabilities=registry)


def _assert_acyclic(registry: dict[str, Capability]) -> None:
    white, grey, black = 0, 1, 2
    color = dict.fromkeys(registry, white)

    def visit(key: str) -> None:
        color[key] = grey
        for dep in registry[key].depends_on:
            if color[dep] == grey:
                raise ValueError(f"capability dependency cycle involving '{key}' -> '{dep}'")
            if color[dep] == white:
                visit(dep)
        color[key] = black

    for key in registry:
        if color[key] == white:
            visit(key)


#: Process-wide default registry.
default_registry: Final[CapabilityRegistry] = build_registry()
