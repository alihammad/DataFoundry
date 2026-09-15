"""SimulatedQualityGateway + live zone adapters (feature 004).

The quality engine never talks to a cloud SDK directly — it goes through a
gateway. :class:`SimulatedQualityGateway` provides in-memory fake zone
inventories + record fixtures so every gate/contract/quarantine/override/score
path is exercisable offline (no docker/terraform/database). Live adapters
(S3/GCS) read the same zone prefixes via the feature 001 ``CloudGateway``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa


@dataclass
class QualityTable:
    """One in-memory dataset table for test evaluation."""

    dataset_id: str
    layer: str  # bronze | silver | gold
    schema: pa.Schema
    rows: list[dict[str, Any]] = field(default_factory=list)


class QualityGateway(abc.ABC):
    """Operations the quality engine needs to evaluate tests."""

    @abc.abstractmethod
    def read_table(self, dataset_id: str, layer: str) -> pa.Table:
        """Read a dataset's records as a PyArrow table."""

    @abc.abstractmethod
    def table_exists(self, dataset_id: str, layer: str) -> bool:
        """Whether a dataset's records exist in the zone."""

    @abc.abstractmethod
    def write_quarantine(
        self, *, dataset_id: str, batch_id: str, payload_ref: str, meta: dict[str, Any]
    ) -> str:
        """Write a quarantined record payload; returns the payload ref."""

    @abc.abstractmethod
    def read_quarantine(self, payload_ref: str) -> dict[str, Any] | None:
        """Read a quarantined record payload."""


class SimulatedQualityGateway(QualityGateway):
    """In-memory quality inventory (dev mode / tests)."""

    def __init__(self) -> None:
        self._tables: dict[str, QualityTable] = {}
        self._quarantine: dict[str, dict[str, Any]] = {}
        self._faults: set[str] = set()  # test hooks

    # -- test hooks ---------------------------------------------------------

    def force_test_error(self, dataset_id: str) -> None:
        """Make test evaluation raise (infrastructure error -> fail closed)."""
        self._faults.add(f"error:{dataset_id}")

    def force_stale_data(self, dataset_id: str) -> None:
        """Mark a dataset's records as stale (freshness test fails)."""
        self._faults.add(f"stale:{dataset_id}")

    def force_volume_anomaly(self, dataset_id: str) -> None:
        """Mark a dataset's volume as anomalous (volume test fails)."""
        self._faults.add(f"volume:{dataset_id}")

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
        self._tables[dataset_id] = QualityTable(
            dataset_id=dataset_id, layer=layer, schema=schema, rows=rows
        )

    # -- QualityGateway --------------------------------------------------------

    def read_table(self, dataset_id: str, layer: str) -> pa.Table:
        table = self._tables.get(dataset_id)
        if table is None or table.layer != layer:
            raise KeyError(f"no {layer} table for dataset {dataset_id}")
        if f"error:{dataset_id}" in self._faults:
            raise RuntimeError(f"simulated test infrastructure error for {dataset_id}")
        return pa.Table.from_pylist(table.rows, schema=table.schema)

    def table_exists(self, dataset_id: str, layer: str) -> bool:
        table = self._tables.get(dataset_id)
        return table is not None and table.layer == layer

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


def build_fixture_schema(columns: dict[str, pa.DataType]) -> pa.Schema:
    """Build a PyArrow schema from a ``{column: type}`` map."""
    return pa.schema([pa.field(name, dtype) for name, dtype in columns.items()])
