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
from contextlib import asynccontextmanager

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
    from datafoundry.controlplane.ingestion.gateway import (
        build_landing_gateway,
        build_source_gateway,
    )
    from datafoundry.controlplane.quality.gateway import build_quality_gateway

    app.state.sessionmaker = get_sessionmaker()
    app.state.gateway = build_gateway(settings)
    app.state.quality_gateway = build_quality_gateway(settings)
    app.state.source_gateway = build_source_gateway(settings)
    app.state.landing_gateway = build_landing_gateway(settings)
    from datafoundry.controlplane.processing.gateway import build_processing_gateway

    app.state.processing_gateway = build_processing_gateway(settings)
    from datafoundry.controlplane.security.gateway import build_security_gateway

    app.state.security_gateway = build_security_gateway(settings)
    from datafoundry.controlplane.semantic.compute.gateway import build_semantic_gateway

    app.state.semantic_gateway = build_semantic_gateway(settings)

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

    # Ingestion dispatcher: hands a queued IngestionRun to the ingestion engine
    # (T022). Tests drive the engine explicitly via process_ingestion_run.
    def _dispatch_ingestion(run_id: uuid.UUID) -> None:
        def _process() -> None:
            session = app.state.sessionmaker()
            try:
                from datafoundry.controlplane.ingestion.engine import run_ingestion

                run_ingestion(
                    session,
                    gateway=app.state.source_gateway,
                    landing=app.state.landing_gateway,
                    run_id=run_id,
                )
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("ingestion.dispatch_failed", extra={"run_id": str(run_id)})
            finally:
                session.close()

        threading.Thread(target=_process, daemon=True, name=f"ingestion-{run_id}").start()

    app.state.ingestion_dispatcher = _dispatch_ingestion

    # In-process ingestion scheduler (T042, R-04): background ticker dispatching
    # due pipelines through the ingestion dispatcher. Started in the app
    # lifespan (not at import) so the module-level ``app = create_app()`` does
    # not spawn a thread that races test teardown. Tests drive ticks directly
    # via IngestionScheduler.tick().
    from datafoundry.controlplane.ingestion.scheduler import IngestionScheduler

    app.state.ingestion_scheduler = IngestionScheduler(
        app.state.sessionmaker,
        dispatcher=_dispatch_ingestion,
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        # Start the in-process ingestion scheduler only when serving (uvicorn /
        # TestClient context). Tests that construct the app without a lifespan
        # drive ticks directly via IngestionScheduler.tick().
        if settings.ingestion_scheduler_enabled:
            app.state.ingestion_scheduler.start()
        try:
            yield
        finally:
            app.state.ingestion_scheduler.stop()

    app = FastAPI(
        title="DataFoundry Control Plane",
        version=settings.service_version,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=_lifespan,
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
    try:  # pragma: no cover
        from datafoundry.controlplane.api import gates as gates_api

        api_router.include_router(gates_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import tests as tests_api

        api_router.include_router(tests_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import contracts as contracts_api

        api_router.include_router(contracts_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import quarantine as quarantine_api

        api_router.include_router(quarantine_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import overrides as overrides_api

        api_router.include_router(overrides_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import quality as quality_api

        api_router.include_router(quality_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import sources as sources_api

        api_router.include_router(sources_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import ingestion_configs as ingestion_configs_api

        api_router.include_router(ingestion_configs_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import (
            ingestion_quarantine as ingestion_quarantine_api,
        )

        api_router.include_router(ingestion_quarantine_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import pipelines as pipelines_api

        api_router.include_router(pipelines_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import ingestion_runs as ingestion_runs_api

        api_router.include_router(ingestion_runs_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import runs

        api_router.include_router(runs.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import datasets as datasets_api

        api_router.include_router(datasets_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import transformations as transformations_api

        api_router.include_router(transformations_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import promotion as promotion_api

        api_router.include_router(promotion_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import lineage as lineage_api

        api_router.include_router(lineage_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import query as query_api

        api_router.include_router(query_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import classification as classification_api

        api_router.include_router(classification_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import protection as protection_api

        api_router.include_router(protection_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import keys as keys_api

        api_router.include_router(keys_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import tokens as tokens_api

        api_router.include_router(tokens_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import access as access_api

        api_router.include_router(access_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import security_audit as security_audit_api

        api_router.include_router(security_audit_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import semantic as semantic_api

        api_router.include_router(semantic_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import metrics as metrics_api

        api_router.include_router(metrics_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import semantic_tests as semantic_tests_api

        api_router.include_router(semantic_tests_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import publications as publications_api

        api_router.include_router(publications_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import discovery as discovery_api

        api_router.include_router(discovery_api.router)
    except ImportError:
        pass
    try:  # pragma: no cover
        from datafoundry.controlplane.api import consumers as consumers_api

        api_router.include_router(consumers_api.router)
    except ImportError:
        pass


#: Module-level app for ``uvicorn datafoundry.controlplane.api.app:app``.
app = create_app()
