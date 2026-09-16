"""Connector ABC for ingestion source types (T008).

Each connector implements :class:`Connector` and is registered in the
connector registry keyed by ``source_type`` (mirrors the capability-registry
pattern). Adding a source type = a new connector module + registry entry only
(FR-015 spirit).
"""

from __future__ import annotations

import abc
from typing import Any


class Connector(abc.ABC):
    """Operations a source connector must provide (research R-01)."""

    #: The ``source_type`` this connector serves (postgres | sqlserver |
    #: object_storage).
    source_type: str = ""

    @abc.abstractmethod
    def discover_schema(self, config_ref: dict[str, Any]) -> dict[str, Any]:
        """Discover a source's schema (tables/columns/types/nullability)."""

    @abc.abstractmethod
    def test_connection(self, config_ref: dict[str, Any]) -> dict[str, Any]:
        """Test connectivity; returns ok + schema or classified error.

        Classified errors: ``authentication_failed``, ``network_unreachable``,
        ``database_not_found``, ``invalid_format`` (US1-AC4).
        """

    @abc.abstractmethod
    def extract(
        self,
        config_ref: dict[str, Any],
        *,
        object_name: str,
        cursor_column: str | None = None,
        watermark: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Extract rows for one source object (optionally incremental)."""
