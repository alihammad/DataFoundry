"""Shared test fixtures.

Contract/integration tests run against an in-memory SQLite database (the ORM
models compile on both dialects; Postgres-specific DDL lives in Alembic
migrations only) and the real FastAPI app with dependency overrides.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("DF_AUTH_MODE", "dev")
os.environ.setdefault("DF_OTEL_ENABLED", "0")
os.environ.setdefault("DF_LOG_JSON", "0")

import pytest
from datafoundry.controlplane.api.app import create_app
from datafoundry.controlplane.config.settings import Settings
from datafoundry.controlplane.db.models import Base
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = REPO_ROOT / "platform-configs" / "examples"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url="sqlite://",
        terraform_root=tmp_path / "terraform",
        otel_enabled=False,
        log_json=False,
        auth_mode="dev",
    )


@pytest.fixture()
def make_settings(tmp_path: Path):
    """Factory for Settings with overrides (e.g. fault injection)."""

    def _make(**overrides) -> Settings:
        base = {
            "database_url": "sqlite://",
            "terraform_root": tmp_path / "terraform",
            "otel_enabled": False,
            "log_json": False,
            "auth_mode": "dev",
        }
        base.update(overrides)
        return Settings(**base)

    return _make


@pytest.fixture()
def session_factory() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite does not enforce foreign keys by default.
    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    # Fresh in-memory DB per test — no drop_all needed (it trips over the
    # circular platform<->config_version FK on SQLite).
    engine.dispose()


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as sess:
        yield sess


@pytest.fixture()
def make_app(make_settings, session_factory):
    """Factory building the FastAPI app with custom settings (fault injection etc.)."""

    def _make(**settings_overrides):
        from datafoundry.controlplane.api.deps import get_db

        settings = make_settings(**settings_overrides)
        application = create_app(settings)
        application.state.sessionmaker = session_factory
        # Tests drive the worker explicitly; no background dispatch.
        application.state.dispatcher = lambda run_id: None

        def _override_get_db() -> Iterator[Session]:
            with session_factory() as sess:
                try:
                    yield sess
                    sess.commit()
                except Exception:
                    sess.rollback()
                    raise

        application.dependency_overrides[get_db] = _override_get_db
        return application

    return _make


@pytest.fixture()
def app(settings: Settings, session_factory: sessionmaker[Session]):
    from datafoundry.controlplane.api.deps import get_db

    application = create_app(settings)
    application.state.sessionmaker = session_factory
    # Tests drive the worker explicitly; no background dispatch.
    application.state.dispatcher = lambda run_id: None

    def _override_get_db() -> Iterator[Session]:
        with session_factory() as sess:
            try:
                yield sess
                sess.commit()
            except Exception:
                sess.rollback()
                raise

    application.dependency_overrides[get_db] = _override_get_db
    return application


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture()
def process_run(app):
    """Drive the deployment worker explicitly (tests use a no-op dispatcher).

    Returns a callable ``process_run(run_id)`` executing the run to its next
    terminal/paused state against the app's gateway.
    """

    def _process(run_id):
        from datafoundry.controlplane.engine.worker import WorkerRunner

        session = app.state.sessionmaker()
        try:
            worker = WorkerRunner(session, settings=app.state.settings, gateway=app.state.gateway)
            run = worker.process_run(run_id)
            session.commit()
            return run
        finally:
            session.close()

    return _process


def load_example(name: str) -> dict:
    import yaml

    return yaml.safe_load((EXAMPLES / name).read_text())
