"""FastAPI application skeleton (T017).

``/api/v1`` base path, RFC 9457 problem+json errors (api/errors.py),
unauthenticated ``GET /healthz``, and router registration points for the
user-story routers (platforms T035, runs T036, validate T037, capabilities
T079).
"""

from __future__ import annotations

from datafoundry.controlplane.api.errors import register_error_handlers
from datafoundry.controlplane.config.settings import Settings, get_settings
from datafoundry.controlplane.observability import setup_observability
from fastapi import APIRouter, FastAPI


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    app = FastAPI(
        title="DataFoundry Control Plane",
        version=settings.service_version,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = settings

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


#: Module-level app for ``uvicorn datafoundry.controlplane.api.app:app``.
app = create_app()
