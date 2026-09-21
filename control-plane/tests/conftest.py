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
        ingestion_scheduler_enabled=False,
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
            "ingestion_scheduler_enabled": False,
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
        application.state.ingestion_dispatcher = lambda run_id: None

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
    application.state.ingestion_dispatcher = lambda run_id: None

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


@pytest.fixture()
def simulated_quality_gateway():
    """In-memory quality gateway for offline gate/contract/quarantine tests."""
    from datafoundry.controlplane.quality.gateway import SimulatedQualityGateway

    return SimulatedQualityGateway()


@pytest.fixture()
def dataset(session_factory: sessionmaker[Session]):
    """Create a minimal Dataset row (feature 003 stub) for quality tests.

    Returns a callable ``dataset(name, layer)`` persisting a Dataset and
    returning its id.
    """

    def _make(name: str = "customer", layer: str = "silver"):
        from datafoundry.controlplane.db.models import (
            Dataset,
            EnvironmentType,
            Platform,
            Provider,
        )

        with session_factory() as sess:
            platform = Platform(
                name="crm-platform",
                provider=Provider.aws,
                cloud_scope_id="scope-1",
                region="us-east-1",
                environment_type=EnvironmentType.test,
                owner_identity="dev@datafoundry.local",
            )
            sess.add(platform)
            sess.flush()
            row = Dataset(
                platform_id=platform.id,
                name=name,
                layer=layer,
                schema_definition={"customer_id": {"type": "integer", "nullable": False}},
                owner_identity="user@acme.com",
                classification="internal",
            )
            sess.add(row)
            sess.commit()
            return row.id

    return _make


@pytest.fixture()
def ui_caller(settings: Settings):
    """Authenticated UI caller identity (feature 007)."""
    from datafoundry.controlplane.api.auth import Caller

    return Caller(identity=settings.dev_identity)


@pytest.fixture()
def saved_query(session_factory: sessionmaker[Session]):
    """Create a minimal SavedQuery row (feature 007).

    Returns a callable ``saved_query(name, owner)`` persisting a SavedQuery
    and returning its id.
    """

    def _make(name: str = "revenue", owner: str = "dev@datafoundry.local"):
        from datafoundry.controlplane.db.models import SavedQuery

        with session_factory() as sess:
            row = SavedQuery(
                name=name,
                owner_identity=owner,
                sql_text="SELECT * FROM gold_orders",
                dataset_bindings=["gold_orders"],
                sharing="private",
            )
            sess.add(row)
            sess.commit()
            return row.id

    return _make


@pytest.fixture()
def process_ui_action(app):
    """Drive a UI-owned backend action synchronously (feature 007).

    Returns a callable ``process_ui_action(fn, *args, **kwargs)`` executing
    ``fn`` against the app's session and committing.
    """

    def _process(fn, *args, **kwargs):
        session = app.state.sessionmaker()
        try:
            result = fn(session, *args, **kwargs)
            session.commit()
            return result
        finally:
            session.close()

    return _process


@pytest.fixture()
def process_quality_run(app):
    """Drive the quality engine explicitly (tests use a no-op dispatcher).

    Returns a callable ``process_quality_run(gate_id, run_id, batch_id, env)``
    executing the gate against the app's quality gateway.
    """

    def _process(gate_id, run_id, batch_id, environment="production"):
        from datafoundry.controlplane.quality.engine import run_gate

        session = app.state.sessionmaker()
        try:
            report = run_gate(
                session,
                gateway=app.state.quality_gateway,
                gate_id=gate_id,
                run_id=run_id,
                batch_id=batch_id,
                environment=environment,
            )
            session.commit()
            return report
        finally:
            session.close()

    return _process


@pytest.fixture()
def simulated_source_gateway():
    """In-memory source gateway for offline ingestion tests."""
    from datafoundry.controlplane.ingestion.gateway import SimulatedSourceGateway

    return SimulatedSourceGateway()


@pytest.fixture()
def simulated_processing_gateway():
    """In-memory processing gateway for offline transformation tests."""
    from datafoundry.controlplane.processing.gateway import SimulatedProcessingGateway

    return SimulatedProcessingGateway()


@pytest.fixture()
def simulated_security_gateway():
    """In-memory security gateway for offline protection tests."""
    from datafoundry.controlplane.security.gateway import SimulatedSecurityGateway

    return SimulatedSecurityGateway()


@pytest.fixture()
def simulated_semantic_gateway():
    """In-memory semantic gateway for offline metric/semantic tests."""
    from datafoundry.controlplane.semantic.compute.gateway import SimulatedSemanticGateway

    return SimulatedSemanticGateway()


@pytest.fixture()
def classified_dataset(session_factory: sessionmaker[Session]):
    """Create a minimal Dataset row for security tests.

    Returns a callable ``classified_dataset(name, layer)`` persisting a Dataset
    and returning its id.
    """

    def _make(name: str = "customer", layer: str = "silver"):
        from datafoundry.controlplane.db.models import (
            Dataset,
            EnvironmentType,
            Platform,
            Provider,
        )

        with session_factory() as sess:
            platform = Platform(
                name="crm-platform",
                provider=Provider.aws,
                cloud_scope_id="scope-1",
                region="us-east-1",
                environment_type=EnvironmentType.test,
                owner_identity="dev@datafoundry.local",
            )
            sess.add(platform)
            sess.flush()
            row = Dataset(
                platform_id=platform.id,
                name=name,
                layer=layer,
                schema_definition={"customer_id": {"type": "integer", "nullable": False}},
                owner_identity="dev@datafoundry.local",
                classification="internal",
            )
            sess.add(row)
            sess.commit()
            return row.id

    return _make


@pytest.fixture()
def process_processing_run(app):
    """Drive the processing engine explicitly (tests use a no-op dispatcher).

    Returns a callable ``process_processing_run(transformation_id, dataset_id)``
    executing the transformation against the app's processing gateway.
    """

    def _process(transformation_id, dataset_id):
        from datafoundry.controlplane.processing.engine import run_transformation

        session = app.state.sessionmaker()
        try:
            result = run_transformation(
                session,
                gateway=app.state.processing_gateway,
                transformation_id=transformation_id,
                dataset_id=dataset_id,
            )
            session.commit()
            return result
        finally:
            session.close()

    return _process


@pytest.fixture()
def semantic_dataset(session_factory: sessionmaker[Session]):
    """Create a minimal Dataset row for semantic tests.

    Returns a callable ``semantic_dataset(name, layer)`` persisting a Dataset
    and returning its id.
    """

    def _make(name: str = "orders", layer: str = "gold"):
        from datafoundry.controlplane.db.models import (
            Dataset,
            EnvironmentType,
            Platform,
            Provider,
        )

        with session_factory() as sess:
            platform = Platform(
                name="crm-platform",
                provider=Provider.aws,
                cloud_scope_id="scope-1",
                region="us-east-1",
                environment_type=EnvironmentType.test,
                owner_identity="dev@datafoundry.local",
            )
            sess.add(platform)
            sess.flush()
            row = Dataset(
                platform_id=platform.id,
                name=name,
                layer=layer,
                schema_definition={"order_id": {"type": "integer", "nullable": False}},
                owner_identity="dev@datafoundry.local",
                classification="internal",
            )
            sess.add(row)
            sess.commit()
            return row.id

    return _make


@pytest.fixture()
def process_semantic_query(app):
    """Drive the semantic engine explicitly (tests use a no-op dispatcher).

    Returns a callable ``process_semantic_query(metric_id, ...)`` executing the
    metric query against the app's semantic gateway.
    """

    def _process(metric_id, **kwargs):
        from datafoundry.controlplane.semantic.engine import run_semantic_query

        session = app.state.sessionmaker()
        try:
            result = run_semantic_query(
                session,
                gateway=app.state.semantic_gateway,
                metric_id=metric_id,
                **kwargs,
            )
            session.commit()
            return result
        finally:
            session.close()

    return _process


@pytest.fixture()
def process_ingestion_run(app):
    """Drive the ingestion worker explicitly (tests use a no-op dispatcher).

    Returns a callable ``process_ingestion_run(run_id)`` executing the run to
    its next terminal state against the app's source gateway.
    """

    def _process(run_id):
        from datafoundry.controlplane.ingestion.engine import run_ingestion

        session = app.state.sessionmaker()
        try:
            run = run_ingestion(
                session,
                gateway=app.state.source_gateway,
                run_id=run_id,
            )
            session.commit()
            return run
        finally:
            session.close()

    return _process


def load_example(name: str) -> dict:
    import yaml

    return yaml.safe_load((EXAMPLES / name).read_text())
