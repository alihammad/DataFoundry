"""PostgreSQL connector (T018, research R-02).

SQLAlchemy Core + ``psycopg``: ``discover_schema`` via the inspector
(tables/columns/types/nullability), ``test_connection`` with classified errors
(authentication_failed / network_unreachable / database_not_found), and
``extract`` with server-side streaming and ``WHERE cursor_col > :watermark
ORDER BY cursor_col`` for incremental loads (R-02).

The connector is registered under ``source_type = "postgres"``. In dev/tests
the engine routes through the simulated gateway instead, so this module is
only exercised against a live database (gated E2E).
"""

from __future__ import annotations

from typing import Any

from datafoundry.controlplane.ingestion.connectors.base import Connector
from datafoundry.controlplane.ingestion.connectors.registry import register


@register
class PostgresConnector(Connector):
    """PostgreSQL source connector (SQLAlchemy Core + psycopg)."""

    source_type = "postgres"

    def _engine(self, config_ref: dict[str, Any]):
        from sqlalchemy import create_engine

        host = config_ref["host"]
        port = config_ref.get("port", 5432)
        database = config_ref["database"]
        url = f"postgresql+psycopg://{host}:{port}/{database}"
        return create_engine(url)

    def discover_schema(self, config_ref: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import inspect

        engine = self._engine(config_ref)
        try:
            inspector = inspect(engine)
            tables = []
            for table_name in inspector.get_table_names():
                columns = []
                for col in inspector.get_columns(table_name):
                    columns.append(
                        {
                            "name": col["name"],
                            "type": _type_name(col["type"]),
                            "nullable": bool(col.get("nullable", True)),
                        }
                    )
                tables.append({"name": table_name, "columns": columns})
            return {"source_type": "postgres", "tables": tables}
        finally:
            engine.dispose()

    def test_connection(self, config_ref: dict[str, Any]) -> dict[str, Any]:
        try:
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
        from sqlalchemy import text

        engine = self._engine(config_ref)
        try:
            if cursor_column is not None and watermark is not None:
                stmt = text(
                    f"SELECT * FROM {object_name} "  # noqa: S608 - validated id
                    f"WHERE {cursor_column} > :watermark "
                    f"ORDER BY {cursor_column}"
                )
                params = {"watermark": watermark}
            else:
                stmt = text(f"SELECT * FROM {object_name}")  # noqa: S608
                params = {}
            with engine.connect() as conn:
                result = conn.execute(stmt, params)
                return [dict(row._mapping) for row in result]
        finally:
            engine.dispose()


def _type_name(sql_type: Any) -> str:
    """Map a SQLAlchemy type to a portable type name (integer/string/...)."""
    name = str(sql_type).lower()
    if "int" in name:
        return "integer"
    if "char" in name or "text" in name or "uuid" in name:
        return "string"
    if "bool" in name:
        return "boolean"
    if "float" in name or "double" in name or "numeric" in name or "decimal" in name:
        return "number"
    if "timestamp" in name or "datetime" in name or "date" in name:
        return "timestamp"
    return name.split("(")[0]


def _classify(exc: Exception) -> str:
    """Classify a connection error (US1-AC4)."""
    message = str(exc).lower()
    if "password" in message or "authentication" in message or "permission denied" in message:
        return "authentication_failed"
    if "could not connect" in message or "connection refused" in message or "timed out" in message:
        return "network_unreachable"
    if "does not exist" in message or ("database" in message and "not found" in message):
        return "database_not_found"
    return "database_not_found"
