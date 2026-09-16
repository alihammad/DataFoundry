"""Ingestion gateway abstraction (feature 002).

The ingestion engine never talks to a source SDK directly — it goes through a
gateway. :class:`SimulatedSourceGateway` provides in-memory fake PostgreSQL /
SQL Server / object-storage inventories (tables, columns, rows, files,
checksums) with fault-injection hooks so every connector/validation/quarantine
path is exercisable offline (no docker/terraform/database). Live adapters
(psycopg/pymssql/S3/GCS) are added in later phases.
"""

from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SimTable:
    """One in-memory source table."""

    name: str
    columns: list[dict[str, Any]]  # [{name, type, nullable}]
    rows: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SimFile:
    """One in-memory source file (object storage / file drop)."""

    name: str
    content: bytes
    checksum: str = ""
    format: str = "parquet"  # csv | json | parquet


@dataclass
class SimSource:
    """One in-memory source (database or object storage)."""

    source_type: str  # postgres | sqlserver | object_storage
    tables: dict[str, SimTable] = field(default_factory=dict)
    files: dict[str, SimFile] = field(default_factory=dict)


class SourceGateway(abc.ABC):
    """Operations the ingestion engine needs to extract from a source."""

    @abc.abstractmethod
    def discover_schema(self, source_id: str) -> dict[str, Any]:
        """Discover a source's schema (tables/columns/types/nullability)."""

    @abc.abstractmethod
    def test_connection(self, source_id: str) -> dict[str, Any]:
        """Test connectivity; returns ok + discovered schema or classified error."""

    @abc.abstractmethod
    def extract(
        self,
        source_id: str,
        *,
        object_name: str,
        cursor_column: str | None = None,
        watermark: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Extract rows for one source object (optionally incremental)."""

    @abc.abstractmethod
    def list_files(self, source_id: str) -> list[dict[str, Any]]:
        """List files in an object-storage source with metadata + checksums."""

    @abc.abstractmethod
    def read_file(self, source_id: str, file_name: str) -> bytes:
        """Read a file's raw bytes from an object-storage source."""


class SimulatedSourceGateway(SourceGateway):
    """In-memory source inventory (dev mode / tests)."""

    def __init__(self) -> None:
        self._sources: dict[str, SimSource] = {}
        self._faults: set[str] = set()  # test hooks

    # -- test hooks ---------------------------------------------------------

    def force_auth_fail(self, source_id: str) -> None:
        """Make connection test fail with ``authentication_failed``."""
        self._faults.add(f"auth:{source_id}")

    def force_network_unreachable(self, source_id: str) -> None:
        """Make connection test fail with ``network_unreachable``."""
        self._faults.add(f"network:{source_id}")

    def force_database_not_found(self, source_id: str) -> None:
        """Make connection test fail with ``database_not_found``."""
        self._faults.add(f"notfound:{source_id}")

    def force_schema_change(self, source_id: str, table: str) -> None:
        """Mutate a table's schema (e.g. integer -> string) for contract tests."""
        self._faults.add(f"schema_change:{source_id}:{table}")

    def force_corrupt_file(self, source_id: str, file_name: str) -> None:
        """Corrupt a file's bytes so validation fails."""
        self._faults.add(f"corrupt:{source_id}:{file_name}")

    def clear_faults(self) -> None:
        self._faults.clear()

    # -- fixtures -------------------------------------------------------------

    def seed_database(
        self,
        source_id: str,
        *,
        source_type: str = "postgres",
        tables: dict[str, SimTable] | None = None,
    ) -> None:
        """Seed a database source with tables."""
        self._sources[source_id] = SimSource(
            source_type=source_type, tables=tables or {}
        )

    def seed_object_storage(
        self,
        source_id: str,
        *,
        files: dict[str, SimFile] | None = None,
    ) -> None:
        """Seed an object-storage source with files."""
        self._sources[source_id] = SimSource(
            source_type="object_storage", files=files or {}
        )

    def add_table(
        self,
        source_id: str,
        table: SimTable,
        *,
        rows: list[dict[str, Any]] | None = None,
    ) -> None:
        """Add a table (and optional rows) to a database source."""
        source = self._sources[source_id]
        table.rows = rows or []
        source.tables[table.name] = table

    def add_file(
        self,
        source_id: str,
        file_name: str,
        content: bytes,
        *,
        fmt: str = "parquet",
    ) -> None:
        """Add a file to an object-storage source, computing its checksum."""
        source = self._sources[source_id]
        source.files[file_name] = SimFile(
            name=file_name,
            content=content,
            checksum=hashlib.sha256(content).hexdigest(),
            format=fmt,
        )

    # -- SourceGateway ---------------------------------------------------------

    def discover_schema(self, source_id: str) -> dict[str, Any]:
        source = self._sources[source_id]
        return {
            "source_id": source_id,
            "source_type": source.source_type,
            "tables": [
                {"name": t.name, "columns": t.columns}
                for t in source.tables.values()
            ],
        }

    def test_connection(self, source_id: str) -> dict[str, Any]:
        if f"auth:{source_id}" in self._faults:
            return {"ok": False, "error": "authentication_failed"}
        if f"network:{source_id}" in self._faults:
            return {"ok": False, "error": "network_unreachable"}
        if f"notfound:{source_id}" in self._faults:
            return {"ok": False, "error": "database_not_found"}
        if source_id not in self._sources:
            return {"ok": False, "error": "database_not_found"}
        return {"ok": True, "discovered_schema": self.discover_schema(source_id)}

    def extract(
        self,
        source_id: str,
        *,
        object_name: str,
        cursor_column: str | None = None,
        watermark: Any | None = None,
    ) -> list[dict[str, Any]]:
        source = self._sources[source_id]
        table = source.tables[object_name]
        rows = table.rows
        if cursor_column is not None and watermark is not None:
            rows = [
                r
                for r in rows
                if r.get(cursor_column) is not None and r[cursor_column] > watermark
            ]
        return list(rows)

    def list_files(self, source_id: str) -> list[dict[str, Any]]:
        source = self._sources[source_id]
        return [
            {
                "name": f.name,
                "size": len(f.content),
                "checksum": f.checksum,
                "format": f.format,
            }
            for f in source.files.values()
        ]

    def read_file(self, source_id: str, file_name: str) -> bytes:
        source = self._sources[source_id]
        file = source.files[file_name]
        if f"corrupt:{source_id}:{file_name}" in self._faults:
            return b"corrupted-bytes-not-a-valid-file"
        return file.content


def build_source_gateway(settings: Any) -> SourceGateway:
    """Build the source gateway for the app (simulated in dev/tests).

    MVP uses the in-memory :class:`SimulatedSourceGateway` so every
    connector/validation/quarantine path is exercisable offline (no
    docker/terraform/database). Live adapters (psycopg/pymssql/S3/GCS) are
    added in later phases.
    """
    return SimulatedSourceGateway()
