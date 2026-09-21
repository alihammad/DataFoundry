"""Static SPA serving for the web UI (feature 007, T003).

Mounts the built ``ui/dist`` directory and serves a catch-all fallback to
``index.html`` for non-API routes so client-side routing works on refresh
(R-05). ``/api/*`` and ``/healthz`` are never swallowed by the fallback.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def mount_ui(app: FastAPI, static_dir: Path, base_path: str) -> None:
    """Mount the built SPA at ``base_path`` with an SPA fallback.

    If ``static_dir`` does not exist (e.g. UI not built in a backend-only
    dev/test run), the mount is skipped so the API still works.
    """
    if not static_dir.is_dir():
        return

    index_file = static_dir / "index.html"
    if not index_file.is_file():
        return

    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            f"{base_path.rstrip('/')}/assets",
            StaticFiles(directory=assets_dir),
            name="ui-assets",
        )

    @app.get(f"{base_path.rstrip('/')}/{{path:path}}", include_in_schema=False)
    async def spa_fallback(path: str) -> FileResponse:
        # Never serve the SPA for API or health routes.
        if path.startswith("api/") or path == "healthz":
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")
        candidate = static_dir / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index_file)
