"""Category -> test implementation registry (T008, R-01).

Maps a test ``category`` to its :class:`Test` implementation, mirroring the
capability-registry pattern (FR-015 spirit): adding a test category = one
module + one registration entry, no core change.

The concrete category implementations land in ``tests/categories.py``
(T016/T017). This module owns the registry and the resolution helper used by
the engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from datafoundry.controlplane.config.quality_schema import CATEGORIES

if TYPE_CHECKING:
    from datafoundry.controlplane.quality.tests.base import Test


class UnknownTestCategoryError(KeyError):
    """Raised when a config references a category with no implementation."""


class TestRegistry:
    """Immutable-ish registry of test category implementations."""

    def __init__(self) -> None:
        self._implementations: dict[str, type[Test]] = {}

    def register(self, category: str, implementation: type[Test]) -> None:
        """Register a test implementation for ``category``."""
        if category not in CATEGORIES:
            raise UnknownTestCategoryError(
                f"unknown test category '{category}'; expected one of {CATEGORIES}"
            )
        self._implementations[category] = implementation

    def get(self, category: str) -> type[Test]:
        """Resolve the implementation for ``category``."""
        try:
            return self._implementations[category]
        except KeyError:
            raise UnknownTestCategoryError(
                f"no test implementation registered for category '{category}'"
            ) from None

    def has(self, category: str) -> bool:
        return category in self._implementations

    def categories(self) -> tuple[str, ...]:
        return tuple(self._implementations)


#: Process-wide default registry (mirrors capability ``default_registry``).
_default_registry: TestRegistry | None = None


def default_registry() -> TestRegistry:
    """Return the process-wide test registry, building it on first use."""
    global _default_registry
    if _default_registry is None:
        _default_registry = TestRegistry()
        # Concrete category implementations are registered here (T016/T017).
        # Imported lazily so the registry module stays import-light and the
        # categories module can import the registry without a cycle.
        from datafoundry.controlplane.quality.tests import categories

        categories.register_all(_default_registry)
    return _default_registry


def resolve_test(category: str) -> type[Test]:
    """Resolve the test implementation class for ``category``."""
    return default_registry().get(category)


__all__ = [
    "TestRegistry",
    "UnknownTestCategoryError",
    "default_registry",
    "resolve_test",
]
