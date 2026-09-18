"""Transformation registry (feature 003, T008).

Maps ``logic.type`` -> transformation implementation. Adding a new
transformation type = new module + registry entry only (FR-015 spirit).
"""

from __future__ import annotations

from datafoundry.controlplane.processing.transformations.base import Transformation


class TransformationRegistry:
    """Registry of transformation implementations by ``logic.type``."""

    def __init__(self) -> None:
        self._impls: dict[str, type[Transformation]] = {}

    def register(self, impl: type[Transformation]) -> None:
        self._impls[impl.logic_type] = impl

    def resolve(self, logic_type: str) -> Transformation:
        if logic_type not in self._impls:
            raise KeyError(f"no transformation implementation for logic.type '{logic_type}'")
        return self._impls[logic_type]()

    def types(self) -> list[str]:
        return sorted(self._impls)


default_registry = TransformationRegistry()


def resolve_transformation(logic_type: str) -> Transformation:
    """Resolve a transformation implementation by ``logic.type``."""
    register_all()
    return default_registry.resolve(logic_type)


def register_all() -> None:
    """Register every built-in transformation type (idempotent)."""
    from datafoundry.controlplane.processing.transformations.gold import GoldTransformation
    from datafoundry.controlplane.processing.transformations.silver import (
        SilverTransformation,
    )

    for impl in (SilverTransformation, GoldTransformation):
        if impl.logic_type not in default_registry._impls:
            default_registry.register(impl)


def build_registry() -> TransformationRegistry:
    """Build a registry with all built-in transformations."""
    register_all()
    return default_registry
