"""Semantic gateway abstraction (feature 006, T003).

The semantic engine never talks to a cloud SDK directly — it goes through a
gateway. :class:`SimulatedSemanticGateway` provides in-memory fake Gold/Silver
zone inventories + reference-data fixtures (known revenue/order/customer tables
with duplicates, protected columns, row-level restrictions, staleness,
quality-state flags) with fault-injection hooks (``force_stale_data``,
``force_quality_failure``, ``force_fanout``) so every metric-definition,
semantic-test, publication, access, and discovery path is exercisable offline
(no docker/terraform/database). Live adapters (S3/GCS) are added later.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any

import pyarrow as pa


@dataclass
class ZoneTable:
    """One in-memory dataset table in a zone (silver/gold)."""

    dataset_id: str
    layer: str  # silver | gold
    schema: pa.Schema
    rows: list[dict[str, Any]] = field(default_factory=list)
    #: Protected columns (feature 005) — values must be masked/tokenised.
    protected_columns: list[str] = field(default_factory=list)
    #: Row-level restrictions: role -> list of row predicates (feature 005).
    row_restrictions: dict[str, list[str]] = field(default_factory=dict)
    #: Quality-state flag (feature 004): pass | fail | stale.
    quality_state: str = "pass"
    #: Freshness: last updated timestamp (ISO) for staleness detection.
    last_updated: str | None = None


class SemanticGateway(abc.ABC):
    """Operations the semantic engine needs to read Gold/Silver data."""

    @abc.abstractmethod
    def read_table(self, dataset_id: str, layer: str) -> pa.Table:
        """Read a dataset's current records as a PyArrow table."""

    @abc.abstractmethod
    def table_exists(self, dataset_id: str, layer: str) -> bool:
        """Whether a dataset's records exist in the zone."""

    @abc.abstractmethod
    def table_metadata(self, dataset_id: str, layer: str) -> dict[str, Any]:
        """Return table metadata: protected columns, row restrictions,
        quality state, freshness."""


class SimulatedSemanticGateway(SemanticGateway):
    """In-memory semantic inventory (dev mode / tests)."""

    def __init__(self) -> None:
        self._tables: dict[str, ZoneTable] = {}
        self._faults: set[str] = set()  # test hooks
        self._seed_reference_data()

    # -- test hooks ---------------------------------------------------------

    def force_stale_data(self) -> None:
        """Make all tables report stale freshness (FR-008)."""
        self._faults.add("stale_data")

    def force_quality_failure(self) -> None:
        """Make all tables report a failing quality state (FR-014)."""
        self._faults.add("quality_failure")

    def force_fanout(self) -> None:
        """Make relationship joins fan out (double-counting, R-04)."""
        self._faults.add("fanout")

    def clear_faults(self) -> None:
        self._faults.clear()

    # -- reference-data fixtures --------------------------------------------

    def _seed_reference_data(self) -> None:
        """Seed known revenue/order/customer tables (T003).

        - ``orders`` (gold): order_id, customer_id, amount, region, order_date.
          Contains duplicate order_ids to exercise fan-out detection.
        - ``customers`` (silver): customer_id, name, email (protected),
          segment. Contains a row-level restriction on segment='vip'.
        """
        orders_schema = pa.schema(
            [
                ("order_id", pa.int64()),
                ("customer_id", pa.int64()),
                ("amount", pa.float64()),
                ("region", pa.string()),
                ("order_date", pa.string()),
            ]
        )
        orders_rows = [
            {
                "order_id": 1,
                "customer_id": 101,
                "amount": 100.0,
                "region": "us",
                "order_date": "2026-01-01",
            },
            {
                "order_id": 2,
                "customer_id": 102,
                "amount": 250.0,
                "region": "eu",
                "order_date": "2026-01-02",
            },
            {
                "order_id": 3,
                "customer_id": 101,
                "amount": 75.0,
                "region": "us",
                "order_date": "2026-01-03",
            },
            # Duplicate order_id 4 -> fan-out / double-counting risk.
            {
                "order_id": 4,
                "customer_id": 103,
                "amount": 50.0,
                "region": "eu",
                "order_date": "2026-01-04",
            },
            {
                "order_id": 4,
                "customer_id": 103,
                "amount": 50.0,
                "region": "eu",
                "order_date": "2026-01-04",
            },
        ]
        self._tables["orders"] = ZoneTable(
            dataset_id="orders",
            layer="gold",
            schema=orders_schema,
            rows=orders_rows,
            quality_state="pass",
            last_updated="2026-09-20T00:00:00Z",
        )

        customers_schema = pa.schema(
            [
                ("customer_id", pa.int64()),
                ("name", pa.string()),
                ("email", pa.string()),
                ("segment", pa.string()),
            ]
        )
        customers_rows = [
            {"customer_id": 101, "name": "Alice", "email": "alice@x.com", "segment": "standard"},
            {"customer_id": 102, "name": "Bob", "email": "bob@x.com", "segment": "vip"},
            {"customer_id": 103, "name": "Carol", "email": "carol@x.com", "segment": "standard"},
        ]
        self._tables["customers"] = ZoneTable(
            dataset_id="customers",
            layer="silver",
            schema=customers_schema,
            rows=customers_rows,
            protected_columns=["email"],
            row_restrictions={"analyst": ["segment != 'vip'"]},
            quality_state="pass",
            last_updated="2026-09-20T00:00:00Z",
        )

    # -- SemanticGateway ------------------------------------------------------

    def read_table(self, dataset_id: str, layer: str) -> pa.Table:
        table = self._tables.get(dataset_id)
        if table is None or table.layer != layer:
            raise KeyError(f"no {layer} table {dataset_id}")
        return pa.Table.from_pylist(table.rows, schema=table.schema)

    def table_exists(self, dataset_id: str, layer: str) -> bool:
        table = self._tables.get(dataset_id)
        return table is not None and table.layer == layer

    def table_metadata(self, dataset_id: str, layer: str) -> dict[str, Any]:
        table = self._tables.get(dataset_id)
        if table is None or table.layer != layer:
            raise KeyError(f"no {layer} table {dataset_id}")
        quality_state = table.quality_state
        if "quality_failure" in self._faults:
            quality_state = "fail"
        last_updated = table.last_updated
        if "stale_data" in self._faults:
            last_updated = "2020-01-01T00:00:00Z"
        return {
            "dataset_id": table.dataset_id,
            "layer": table.layer,
            "protected_columns": list(table.protected_columns),
            "row_restrictions": dict(table.row_restrictions),
            "quality_state": quality_state,
            "last_updated": last_updated,
        }


def build_semantic_gateway(settings: Any) -> SemanticGateway:
    """Build the semantic gateway for the app (simulated in dev/tests).

    MVP uses the in-memory :class:`SimulatedSemanticGateway` so every
    metric-definition, semantic-test, publication, access, and discovery path
    is exercisable offline. Live zone adapters are added later.
    """
    return SimulatedSemanticGateway()
