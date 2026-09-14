"""FastAPI application skeleton (T017).

``/api/v1`` base path, RFC 9457 problem+json errors (api/errors.py),
unauthenticated ``GET /healthz``, and router registration points for the
user-story routers (platforms T035, runs T036, validate T037, capabilities
T079).
"""

from __future__ import annotations

import logging
import threading
import uuid

from datafoundry.controlplane.api.errors import register_error_handlers
from datafoundry.controlplane.config.settings import Settings, get_settings
from datafoundry.controlplane.observability import setup_observability
from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)


def _wire_runtime(app: FastAPI, settings: Settings) -> None:
    """Attach the DB sessionmaker, cloud gateway, worker and dispatch hook.

    The dispatcher runs the (synchronous) worker in a background thread so
    POST /platforms returns 202 immediately while the run executes (async
    model, deployment-api.md cross-cutting rules). Tests override
    ``app.state.dispatcher`` with a no-op and drive the worker explicitly.
    """
    from datafoundry.controlplane.db.session import get_sessionmaker
    from datafoundry.controlplane.engine.gateway import build_gateway

    app.state.sessionmaker = get_sessionmaker()
    app.state.gateway = build_gateway(settings)

    def _dispatch(run_id: uuid.UUID) -> None:
        def _process() -> None:
            session = app.state.sessionmaker()
            try:
                from datafoundry.controlplane.engine.worker import WorkerRunner

                worker = WorkerRunner(session, settings=settings, gateway=app.state.gateway)
                worker.process_run(run_id)
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("run.dispatch_failed", extra={"run_id": str(run_id)})
            finally:
                session.close()

        threading.Thread(target=_process, daemon=True, name=f"run-{run_id}").start()

    app.state.dispatcher = _dispatch


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="DataFoundry Control Plane",
        version=settings.service_version,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings
    _wire_runtime(app, settings)

    setup_observability(app, settings)
    register_error_handlers(app)

    # -- unauthenticated liveness (deployment-api.md §4) ----------------------

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": settings.service_version}

    # -- /api/v1 router registration point ------------------------------------
    api_router = APIRouter(prefix=settings.api_prefix)
    _register_routers(api_router)
    app.include_router(api_router)

    return app


def _register_routers(api_router: APIRouter) -> None:
    """Register feature routers as they land.

    Phase 3+ routers (imported lazily to keep the foundational skeleton free
    of unimplemented modules):
      - platforms: datafoundry.controlplane.api.platforms (T035)
      - runs:      datafoundry.controlplane.api.runs      (T036)
      - validate:  datafoundry.controlplane.api.validate  (T037)
      - capabilities: datafoundry.controlplane.api.capabilities (T079)
    """
    try:  # pragma: no cover - routers appear in later phases
        from datafoundry.controlplane.api import platforms

        api_router.include_router(platforms.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import runs

        api_router.include_router(runs.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import validate as validate_api

        api_router.include_router(validate_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import capabilities as capabilities_api

        api_router.include_router(capabilities_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import health as health_api

        api_router.include_router(health_api.router)
    except ImportError:
        pass


#: Module-level app for ``uvicorn datafoundry.controlplane.api.app:app``.
app = create_app()
