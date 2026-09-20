"""Semantic test categories (feature 006, T025).

calculation, reconciliation, relationship, filter; run at publish time AND on
schedule against production data (FR-014).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datafoundry.controlplane.semantic.tests.registry import SemanticTestRegistry


def register_all(registry: SemanticTestRegistry) -> None:
    """Register the semantic test category implementations (T025).

    Concrete implementations land in Phase 4 (US2). Until then the registry
    resolves no categories.
    """
