"""Category -> test implementation registry (feature 006, T009, R-04).

Maps a semantic test ``category`` to its :class:`SemanticTest` implementation,
mirroring the feature 004 quality-test registry pattern: adding a test category
= one module + one registration entry, no core change.

The concrete category implementations land in ``tests/categories.py`` (T025).
This module owns the registry and the resolution helper used by the engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datafoundry.controlplane.config.semantic_schema import CATEGORY_REQUIRED_PARAMETERS

if TYPE_CHECKING:
    from datafoundry.controlplane.semantic.tests.base import SemanticTest


class UnknownSemanticTestCategoryError(KeyError):
    """Raised when a config references a category with no implementation."""


class SemanticTestRegistry:
    """Immutable-ish registry of semantic test category implementations."""

    def __init__(self) -> None:
        self._implementations: dict[str, type[SemanticTest]] = {}

    def register(self, category: str, implementation: type[SemanticTest]) -> None:
        """Register a test implementation for ``category``."""
        if category not in CATEGORY_REQUIRED_PARAMETERS:
            raise UnknownSemanticTestCategoryError(
                f"unknown semantic test category '{category}'; expected one of "
                f"{tuple(CATEGORY_REQUIRED_PARAMETERS)}"
            )
        self._implementations[category] = implementation

    def get(self, category: str) -> type[SemanticTest]:
        """Resolve the implementation for ``category``."""
        try:
            return self._implementations[category]
        except KeyError:
            raise UnknownSemanticTestCategoryError(
                f"no semantic test implementation registered for category '{category}'"
            ) from None

    def has(self, category: str) -> bool:
        return category in self._implementations

    def categories(self) -> tuple[str, ...]:
        return tuple(self._implementations)


#: Process-wide default registry (mirrors capability ``default_registry``).
_default_registry: SemanticTestRegistry | None = None


def default_registry() -> SemanticTestRegistry:
    """Return the process-wide semantic test registry, building it on first use."""
    global _default_registry
    if _default_registry is None:
        _default_registry = SemanticTestRegistry()
        # Concrete category implementations are registered here (T025).
        # Imported lazily so the registry module stays import-light and the
        # categories module can import the registry without a cycle.
        from datafoundry.controlplane.semantic.tests import categories

        categories.register_all(_default_registry)
    return _default_registry


def resolve_test(category: str) -> type[SemanticTest]:
    """Resolve the semantic test implementation class for ``category``."""
    return default_registry().get(category)


__all__ = [
    "SemanticTestRegistry",
    "UnknownSemanticTestCategoryError",
    "default_registry",
    "resolve_test",
]
