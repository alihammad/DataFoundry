"""API router: data sources (T020, contracts/ingestion-api.md §1).

- ``POST /sources`` — register a source (FR-002): validate (all errors at once)
  -> persist DataSource -> audit ``source.registered`` -> 201. 422 on unknown
  type / bad secretRef naming / missing fields / secret-scan hit; 409 on
  duplicate (platform_id, name).
- ``POST /sources/{id}/test`` — test connectivity (FR-004): ok:true with
  discovered_schema, or ok:false with a classified detail
  (authentication_failed / network_unreachable / database_not_found);
  credentials never echoed. Updates connection_state + audit ``source.tested``.
- ``GET /sources`` — list sources visible to the caller.
- ``GET /sources/{id}`` — source detail with secretRef name only (never a value).
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db, get_source_gateway
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    ConflictError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.source_schema import (
    SourceRegistrationError,
    validate_source_registration,
)
from datafoundry.controlplane.db.models import (
    ConnectionState,
    DataSource,
    Platform,
    SourceType,
)
from datafoundry.controlplane.ingestion.gateway import SourceGateway
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["sources"])


# -- response models ------------------------------------------------------------


class SourceRegistered(BaseModel):
    source_id: uuid.UUID


class DiscoveredColumn(BaseModel):
    name: str
    type: str
    nullable: bool


class DiscoveredObject(BaseModel):
    object: str
    columns: list[DiscoveredColumn]


class TestResult(BaseModel):
    ok: bool
    detail: str | None = None
    message: str | None = None
    discovered_schema: list[DiscoveredObject] | None = None


class SourceItem(BaseModel):
    source_id: uuid.UUID
    name: str
    type: str
    owner: str
    connection_state: str
    last_test_at: str | None = None


class SourceList(BaseModel):
    items: list[SourceItem]


class SourceDetail(BaseModel):
    source_id: uuid.UUID
    name: str
    type: str
    owner: str
    connection_state: str
    last_test_at: str | None = None
    config: dict[str, Any]


# -- helpers ---------------------------------------------------------------------


def _get_source(session: Session, source_id: uuid.UUID) -> DataSource:
    source = session.get(DataSource, source_id)
    if source is None:
        raise NotFoundError(f"no source with id {source_id}")
    return source


def _detail(source: DataSource) -> SourceDetail:
    return SourceDetail(
        source_id=source.id,
        name=source.name,
        type=source.type.value,
        owner=source.owner_identity,
        connection_state=source.connection_state.value,
        last_test_at=source.last_test_at.isoformat() if source.last_test_at else None,
        config=dict(source.config_ref or {}),
    )


# -- routes ----------------------------------------------------------------------


@router.post("/sources", status_code=201, response_model=SourceRegistered)
def register_source(
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> SourceRegistered:
    """Register a data source (FR-002)."""
    try:
        registration = validate_source_registration(body)
    except SourceRegistrationError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": _error_path(msg),
                    "code": "invalid_value",
                    "message": msg,
                    "remediation": (
                        "Correct the source registration per contracts/ingestion-api.md §1"
                    ),
                }
                for msg in exc.errors
            ]
        ) from exc

    platform = session.get(Platform, uuid.UUID(registration.platform_id))
    if platform is None:
        raise NotFoundError(f"no platform with id {registration.platform_id}")

    existing = session.execute(
        select(DataSource).where(
            DataSource.platform_id == platform.id,
            DataSource.name == registration.name,
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ConflictError("name_taken", f"source name '{registration.name}' already registered")

    source = DataSource(
        platform_id=platform.id,
        name=registration.name,
        type=SourceType(registration.type),
        config_ref=registration.config,
        owner_identity=caller.identity,
        connection_state=ConnectionState.untested,
    )
    session.add(source)
    session.flush()

    AuditService(session).source_registered(
        actor=caller.identity,
        platform_id=platform.id,
        source_id=source.id,
        source_name=source.name,
        source_type=source.type.value,
    )
    session.flush()
    return SourceRegistered(source_id=source.id)


@router.post("/sources/{source_id}/test", response_model=TestResult)
def test_source(
    source_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    gateway: SourceGateway = Depends(get_source_gateway),
) -> TestResult:
    """Test connectivity (FR-004, US1-AC1/AC4)."""
    source = _get_source(session, source_id)
    result = gateway.test_connection(str(source.id))

    if result["ok"]:
        source.connection_state = ConnectionState.ok
        source.last_test_detail = None
        schema = result["discovered_schema"]
        discovered = [
            DiscoveredObject(
                object=table["name"],
                columns=[
                    DiscoveredColumn(
                        name=col["name"],
                        type=col["type"],
                        nullable=bool(col.get("nullable", True)),
                    )
                    for col in table["columns"]
                ],
            )
            for table in schema.get("tables", [])
        ]
        detail = None
        message = None
    else:
        source.connection_state = ConnectionState.failed
        source.last_test_detail = result["error"]
        detail = result["error"]
        message = result.get("message")
        discovered = None

    source.last_test_at = _now()
    session.flush()

    AuditService(session).source_tested(
        actor=caller.identity,
        platform_id=source.platform_id,
        source_id=source.id,
        ok=result["ok"],
        detail=detail,
    )
    session.flush()
    return TestResult(
        ok=result["ok"],
        detail=detail,
        message=message,
        discovered_schema=discovered,
    )


@router.get("/sources", response_model=SourceList)
def list_sources(
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> SourceList:
    """List sources visible to the caller."""
    sources = session.execute(select(DataSource).order_by(DataSource.created_at)).scalars()
    return SourceList(
        items=[
            SourceItem(
                source_id=s.id,
                name=s.name,
                type=s.type.value,
                owner=s.owner_identity,
                connection_state=s.connection_state.value,
                last_test_at=s.last_test_at.isoformat() if s.last_test_at else None,
            )
            for s in sources
        ]
    )


@router.get("/sources/{source_id}", response_model=SourceDetail)
def get_source(
    source_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> SourceDetail:
    """Source detail with secretRef name only (never a value)."""
    source = _get_source(session, source_id)
    return _detail(source)


def _error_path(msg: str) -> str:
    return msg.split(":", 1)[0] if ":" in msg else "$"


def _now():
    from datetime import UTC, datetime

    return datetime.now(UTC)
