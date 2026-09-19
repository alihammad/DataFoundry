"""Processing gateway abstraction (feature 003).

The processing engine never talks to a cloud SDK directly — it goes through a
gateway. :class:`SimulatedProcessingGateway` provides in-memory fake zone
inventories + record fixtures + Iceberg-in-memory (snapshot/commit semantics)
with fault-injection hooks so every transformation/promotion/lineage/query
path is exercisable offline (no docker/terraform/database). Live adapters
(S3/GCS Iceberg) are added later.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa


@dataclass
class ZoneTable:
    """One in-memory dataset table in a zone (bronze/silver/gold)."""

    dataset_id: str
    layer: str  # bronze | silver | gold
    schema: pa.Schema
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: Iceberg-in-memory: committed snapshots keyed by version (FR-012).
    snapshots: dict[int, list[dict[str, Any]]] = field(default_factory=dict)
    current_version: int = 0


class ProcessingGateway(abc.ABC):
    """Operations the processing engine needs to transform/promote/query."""

    @abc.abstractmethod
    def read_table(self, dataset_id: str, layer: str) -> pa.Table:
        """Read a dataset's current records as a PyArrow table."""

    @abc.abstractmethod
    def table_exists(self, dataset_id: str, layer: str) -> bool:
        """Whether a dataset's records exist in the zone."""

    @abc.abstractmethod
    def write_snapshot(
        self,
        *,
        dataset_id: str,
        layer: str,
        schema: pa.Schema,
        rows: list[dict[str, Any]],
        version: int,
    ) -> str:
        """Atomically commit a new version (Iceberg snapshot, FR-012).

        Returns the table ref. Consumers see either the previous or new
        version, never a torn mix.
        """

    @abc.abstractmethod
    def read_version(self, dataset_id: str, layer: str, version: int) -> pa.Table:
        """Read a specific committed version (time travel, FR-019)."""

    @abc.abstractmethod
    def write_quarantine(
        self, *, dataset_id: str, batch_id: str, payload_ref: str, meta: dict[str, Any]
    ) -> str:
        """Write a quarantined record payload; returns the payload ref."""

    @abc.abstractmethod
    def read_quarantine(self, payload_ref: str) -> dict[str, Any] | None:
        """Read a quarantined record payload."""


class SimulatedProcessingGateway(ProcessingGateway):
    """In-memory processing inventory (dev mode / tests)."""

    def __init__(self) -> None:
        self._tables: dict[str, ZoneTable] = {}
        self._quarantine: dict[str, dict[str, Any]] = {}
        self._faults: set[str] = set()  # test hooks
        #: Column-level protection policy ``{column: "mask" | "tokenise"}``
        #: applied on download (FR-016, US5-AC3).
        self.protection_policy: dict[str, str] = {}

    # -- test hooks ---------------------------------------------------------

    def force_immutability_violation(self, dataset_id: str) -> None:
        """Make a Bronze write raise (immutability violation, FR-002)."""
        self._faults.add(f"immutable:{dataset_id}")

    def force_reconciliation_fail(self, dataset_id: str) -> None:
        """Make Gold reconciliation fail (FR-010)."""
        self._faults.add(f"reconcile:{dataset_id}")

    def force_zero_records(self, dataset_id: str) -> None:
        """Make a transformation produce zero records (FR-020)."""
        self._faults.add(f"zero:{dataset_id}")

    def clear_faults(self) -> None:
        self._faults.clear()

    # -- fixtures -------------------------------------------------------------

    def seed_table(
        self,
        dataset_id: str,
        layer: str,
        schema: pa.Schema,
        rows: list[dict[str, Any]],
    ) -> None:
        """Seed a dataset's records for offline test evaluation."""
        self._tables[dataset_id] = ZoneTable(
            dataset_id=dataset_id, layer=layer, schema=schema, rows=rows
        )

    # -- ProcessingGateway -----------------------------------------------------

    def read_table(self, dataset_id: str, layer: str) -> pa.Table:
        table = self._tables.get(dataset_id)
        if table is None or table.layer != layer:
            raise KeyError(f"no {layer} table for dataset {dataset_id}")
        return pa.Table.from_pylist(table.rows, schema=table.schema)

    def table_exists(self, dataset_id: str, layer: str) -> bool:
        table = self._tables.get(dataset_id)
        return table is not None and table.layer == layer

    def write_snapshot(
        self,
        *,
        dataset_id: str,
        layer: str,
        schema: pa.Schema,
        rows: list[dict[str, Any]],
        version: int,
    ) -> str:
        if f"immutable:{dataset_id}" in self._faults and layer == "bronze":
            raise RuntimeError(f"simulated immutability violation for {dataset_id}")
        if f"zero:{dataset_id}" in self._faults:
            rows = []
        table = self._tables.setdefault(
            dataset_id, ZoneTable(dataset_id=dataset_id, layer=layer, schema=schema)
        )
        table.layer = layer
        table.schema = schema
        table.rows = rows
        table.snapshots[version] = rows
        table.current_version = version
        return f"{layer}/{dataset_id}/v{version}"

    def read_version(self, dataset_id: str, layer: str, version: int) -> pa.Table:
        table = self._tables.get(dataset_id)
        if table is None or table.layer != layer:
            raise KeyError(f"no {layer} table for dataset {dataset_id}")
        rows = table.snapshots.get(version)
        if rows is None:
            raise KeyError(f"no version {version} for dataset {dataset_id}")
        return pa.Table.from_pylist(rows, schema=table.schema)

    def write_quarantine(
        self, *, dataset_id: str, batch_id: str, payload_ref: str, meta: dict[str, Any]
    ) -> str:
        self._quarantine[payload_ref] = {
            "dataset_id": dataset_id,
            "batch_id": batch_id,
            "payload_ref": payload_ref,
            **meta,
        }
        return payload_ref

    def read_quarantine(self, payload_ref: str) -> dict[str, Any] | None:
        return self._quarantine.get(payload_ref)


def build_processing_gateway(settings: Any) -> ProcessingGateway:
    """Build the processing gateway for the app (simulated in dev/tests).

    MVP uses the in-memory :class:`SimulatedProcessingGateway` so every
    transformation/promotion/lineage/query path is exercisable offline (no
    docker/terraform/database). Live S3/GCS Iceberg adapters are added later.
    """
    return SimulatedProcessingGateway()
