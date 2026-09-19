"""Shared FastAPI dependencies (DB session, services, dispatch hook).

Routers depend on these accessors rather than module-level singletons so
tests can override them cleanly (dependency_overrides) and the app can be
constructed with per-instance settings/sessionmakers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from datafoundry.controlplane.config.settings import Settings
from fastapi import Request
from sqlalchemy.orm import Session


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    """Transactional DB session bound to the app's sessionmaker."""
    sessionmaker = request.app.state.sessionmaker
    session = sessionmaker()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_dispatcher(request: Request) -> Callable[[Any], None]:
    """Hook that hands a queued run to the deployment worker (T032).

    Production: starts the async worker loop for the run. Tests: no-op —
    the worker is driven explicitly.
    """
    return request.app.state.dispatcher


def get_cloud_gateway(request: Request) -> Any:
    """Cloud gateway for init jobs / health checks (simulated in dev/tests)."""
    return request.app.state.gateway


def get_quality_gateway(request: Request) -> Any:
    """Quality gateway for gate/contract/quarantine evaluation (simulated)."""
    return request.app.state.quality_gateway


def get_source_gateway(request: Request) -> Any:
    """Source gateway for ingestion connectivity/schema (simulated)."""
    return request.app.state.source_gateway


def get_ingestion_dispatcher(request: Request) -> Callable[[Any], None]:
    """Hook that hands a queued IngestionRun to the ingestion engine (T022).

    Production: starts the ingestion worker loop for the run. Tests: no-op —
    the worker is driven explicitly via ``process_ingestion_run``.
    """
    return request.app.state.ingestion_dispatcher


def get_processing_gateway(request: Request) -> Any:
    """Processing gateway for transformations/promotion (simulated)."""
    return request.app.state.processing_gateway


def get_security_gateway(request: Request) -> Any:
    """Security gateway for classification/protection/keys/tokens (simulated)."""
    return request.app.state.security_gateway


def get_landing_gateway(request: Request) -> Any:
    """Landing gateway for Bronze ingestion writes (simulated)."""
    return request.app.state.landing_gateway
