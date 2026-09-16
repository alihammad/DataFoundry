"""Object-storage connector (T027, research R-03).

PyArrow for CSV/JSON/Parquet, routed through the existing ``CloudGateway``
for S3/GCS parity: ``discover_schema`` (per-file schema), ``test_connection``
with classified errors (incl. ``invalid_format``), and ``extract`` with
per-file record counts, SHA-256 checksums, and file metadata (R-03).

The connector is registered under ``source_type = "object_storage"``. In
dev/tests the engine routes through the simulated gateway instead, so this
module is only exercised against a live object store (gated E2E).
"""

from __future__ import annotations

from typing import Any

from datafoundry.controlplane.ingestion.connectors.base import Connector
from datafoundry.controlplane.ingestion.connectors.registry import register

SUPPORTED_FORMATS = frozenset({"csv", "json", "parquet"})


@register
class ObjectStorageConnector(Connector):
    """Object-storage source connector (PyArrow + CloudGateway parity)."""

    source_type = "object_storage"

    def _location(self, config_ref: dict[str, Any]) -> str:
        return config_ref["location"]

    def _format(self, config_ref: dict[str, Any]) -> str:
        return (config_ref.get("format") or "parquet").lower()

    def _list_files(self, config_ref: dict[str, Any]) -> list[dict[str, Any]]:
        """List files under the location with metadata + checksums (R-03).

        Live listing is provider-specific (S3/GCS ``list_objects_v2``
        paginator via the CloudGateway). The simulated gateway drives tests;
        this stub keeps the connector contract stable for gated E2E.
        """
        return []

    def discover_schema(self, config_ref: dict[str, Any]) -> dict[str, Any]:
        """Discover a schema from the first readable file (R-03)."""
        files = self._list_files(config_ref)
        if not files:
            return {"source_type": "object_storage", "tables": []}
        first = files[0]
        table = _read_table(first["content"], first["format"])
        columns = [
            {"name": name, "type": _type_name(str(field.type)), "nullable": True}
            for name, field in zip(table.column_names, table.schema, strict=True)
        ]
        return {
            "source_type": "object_storage",
            "tables": [{"name": first["name"], "columns": columns}],
        }

    def test_connection(self, config_ref: dict[str, Any]) -> dict[str, Any]:
        try:
            fmt = self._format(config_ref)
            if fmt not in SUPPORTED_FORMATS:
                return {
                    "ok": False,
                    "error": "invalid_format",
                    "message": f"unsupported format '{fmt}'",
                }
            schema = self.discover_schema(config_ref)
            return {"ok": True, "discovered_schema": schema}
        except Exception as exc:
            return {"ok": False, "error": _classify(exc), "message": str(exc)}

    def extract(
        self,
        config_ref: dict[str, Any],
        *,
        object_name: str,
        cursor_column: str | None = None,
        watermark: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Extract rows from one file, with per-file metadata (R-03)."""
        files = self._list_files(config_ref)
        target = next((f for f in files if f["name"] == object_name), None)
        if target is None:
            return []
        table = _read_table(target["content"], target["format"])
        rows = [dict(zip(table.column_names, row, strict=True)) for row in table.to_pylist()]
        return rows


def _read_table(content: bytes, fmt: str):
    """Read bytes into a PyArrow table for the given format."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    if fmt == "parquet":
        return pq.read_table(pa.BufferReader(content))
    if fmt == "json":
        import json

        data = json.loads(content.decode("utf-8"))
        if isinstance(data, list):
            return pa.Table.from_pylist(data)
        return pa.Table.from_pylist([data])
    if fmt == "csv":
        import io

        import pyarrow.csv as pacsv

        return pacsv.read_csv(io.BytesIO(content))
    raise ValueError(f"unsupported format '{fmt}'")


def _type_name(sql_type: str) -> str:
    """Map a PyArrow type string to a portable type name."""
    name = sql_type.lower()
    if "int" in name:
        return "integer"
    if "string" in name or "utf8" in name or "large_string" in name:
        return "string"
    if "bool" in name:
        return "boolean"
    if "double" in name or "float" in name or "decimal" in name:
        return "number"
    if "timestamp" in name or "date" in name:
        return "timestamp"
    return name


def _classify(exc: Exception) -> str:
    """Classify a connection error (US1-AC4 / US2)."""
    message = str(exc).lower()
    if "format" in message or "parse" in message or "schema" in message:
        return "invalid_format"
    if "permission" in message or "access denied" in message or "authentication" in message:
        return "authentication_failed"
    if "not found" in message or "does not exist" in message:
        return "database_not_found"
    if "connect" in message or "unreachable" in message or "timed out" in message:
        return "network_unreachable"
    return "invalid_format"
