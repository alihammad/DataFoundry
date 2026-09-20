"""Semantic test ABC + result (feature 006, T009, R-04).

Every semantic test category implements :class:`SemanticTest` with an
``evaluate`` operation returning a :class:`SemanticTestResult`. The ABC carries
the test's definition (name, category, parameters). The registry
(``tests/registry.py``) maps ``category`` -> implementation, mirroring the
feature 004 quality-test registry pattern.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

from datafoundry.controlplane.db.models import SemanticTestStatus


@dataclass
class SemanticTestResult:
    """One semantic test's outcome in one run (FR-014)."""

    status: SemanticTestStatus
    measured_value: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        return self.status == SemanticTestStatus.passed


@dataclass
class SemanticTest:
    """Base class for a semantic test category implementation.

    ``evaluate`` receives the data needed to run the test (a DuckDB connection
    over the bound datasets, plus the gateway for metadata) and returns a
    :class:`SemanticTestResult`.
    """

    name: str
    category: str
    parameters: dict[str, Any] = field(default_factory=dict)

    @abc.abstractmethod
    def evaluate(self, conn: Any, *, gateway: Any, **context: Any) -> SemanticTestResult:
        """Evaluate the test against ``conn`` (DuckDB) and ``gateway``."""
