"""Connector registry (T008).

Maps ``source_type`` -> connector class (mirrors the capability-registry
pattern). Connectors register themselves via :func:`register`; the registry
resolves a connector for a source type at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datafoundry.controlplane.ingestion.connectors.base import Connector

_REGISTRY: dict[str, type[Connector]] = {}


def register(connector_cls: type[Connector]) -> type[Connector]:
    """Register a connector class under its ``source_type``."""
    if not connector_cls.source_type:
        raise ValueError("connector must declare a non-empty source_type")
    _REGISTRY[connector_cls.source_type] = connector_cls
    return connector_cls


def resolve(source_type: str) -> type[Connector]:
    """Resolve the connector class for a source type."""
    try:
        return _REGISTRY[source_type]
    except KeyError:
        raise KeyError(f"no connector registered for source type '{source_type}'") from None


def registered_types() -> tuple[str, ...]:
    """Return the registered source types."""
    return tuple(_REGISTRY)


def clear() -> None:
    """Clear the registry (test isolation)."""
    _REGISTRY.clear()
