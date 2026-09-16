"""T015: Contract tests for the ingestion sources API (ingestion-api.md §1).

Covers:
- POST /api/v1/sources: 201 {source_id}; 422 all-errors (unknown type, bad
  secretRef naming, missing fields); no persistence on failure.
- POST /sources/{id}/test: ok:true with discovered_schema; ok:false with
  classified detail (authentication_failed / network_unreachable /
  database_not_found); credentials never echoed.
- GET /sources, GET /sources/{id}: list + detail with secretRef name only.
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.ingestion.gateway import SimTable

PROBLEM_CT = "application/problem+json"


def _db_source(**overrides):
    body = {
        "platform_id": str(uuid.uuid4()),
        "name": "crm-prod",
        "type": "postgres",
        "config": {
            "host": "crm.internal",
            "port": 5432,
            "database": "crm",
            "credentials": {"secretRef": "crm-ro-user"},
        },
    }
    body.update(overrides)
    return body


def _seed_platform(app):
    from datafoundry.controlplane.db.models import (
        EnvironmentType,
        Platform,
        Provider,
    )

    with app.state.sessionmaker() as sess:
        platform = Platform(
            name="crm-platform",
            provider=Provider.aws,
            cloud_scope_id="scope-1",
            region="us-east-1",
            environment_type=EnvironmentType.test,
            owner_identity="dev@datafoundry.local",
        )
        sess.add(platform)
        sess.commit()
        return platform.id


class TestRegisterSource:
    def test_201_shape(self, app, client):
        platform_id = _seed_platform(app)
        response = client.post("/api/v1/sources", json=_db_source(platform_id=str(platform_id)))
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"source_id"}
        uuid.UUID(data["source_id"])

    def test_audit_written(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import AuditRecord

        platform_id = _seed_platform(app)
        body = _db_source(platform_id=str(platform_id))
        assert client.post("/api/v1/sources", json=body).status_code == 201
        with session_factory() as session:
            actions = [r.action for r in session.query(AuditRecord).all()]
        assert "source.registered" in actions

    def test_unknown_source_type_422(self, app, client):
        platform_id = _seed_platform(app)
        response = client.post(
            "/api/v1/sources",
            json=_db_source(platform_id=str(platform_id), type="oracle"),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_bad_secret_ref_naming_422(self, app, client):
        platform_id = _seed_platform(app)
        response = client.post(
            "/api/v1/sources",
            json=_db_source(
                platform_id=str(platform_id),
                config={
                    "host": "crm.internal",
                    "database": "crm",
                    "credentials": {"secretRef": "Bad Secret Ref!"},
                },
            ),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_missing_fields_422(self, app, client):
        platform_id = _seed_platform(app)
        response = client.post(
            "/api/v1/sources",
            json=_db_source(
                platform_id=str(platform_id),
                config={"host": "crm.internal"},  # no database / credentials
            ),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_secret_value_in_config_422(self, app, client):
        """Credentials must be a secretRef pointer, never a literal value (SC-007)."""
        platform_id = _seed_platform(app)
        response = client.post(
            "/api/v1/sources",
            json=_db_source(
                platform_id=str(platform_id),
                config={
                    "host": "crm.internal",
                    "database": "crm",
                    "credentials": {"secretRef": "AKIAIOSFODNN7EXAMPLE"},
                },
            ),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)

    def test_nothing_persisted_on_422(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import DataSource

        platform_id = _seed_platform(app)
        assert (
            client.post(
                "/api/v1/sources",
                json=_db_source(platform_id=str(platform_id), type="oracle"),
            ).status_code
            == 422
        )
        with session_factory() as session:
            assert session.query(DataSource).count() == 0

    def test_unknown_platform_404(self, app, client):
        response = client.post("/api/v1/sources", json=_db_source())
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_CT)

    def test_duplicate_name_409(self, app, client):
        platform_id = _seed_platform(app)
        body = _db_source(platform_id=str(platform_id))
        assert client.post("/api/v1/sources", json=body).status_code == 201
        response = client.post("/api/v1/sources", json=body)
        assert response.status_code == 409
        assert response.headers["content-type"].startswith(PROBLEM_CT)


class TestTestConnection:
    def _register(self, app, client):
        platform_id = _seed_platform(app)
        body = _db_source(platform_id=str(platform_id))
        source_id = client.post("/api/v1/sources", json=body).json()["source_id"]
        # Seed the simulated source inventory for this source id.
        app.state.source_gateway.seed_database(
            str(source_id),
            source_type="postgres",
            tables={
                "customer": SimTable(
                    name="customer",
                    columns=[
                        {"name": "customer_id", "type": "integer", "nullable": False},
                        {"name": "email", "type": "string", "nullable": False},
                    ],
                )
            },
        )
        return source_id

    def test_ok_with_discovered_schema(self, app, client):
        source_id = self._register(app, client)
        response = client.post(f"/api/v1/sources/{source_id}/test")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["ok"] is True
        assert data["detail"] is None
        schema = data["discovered_schema"]
        assert len(schema) == 1
        assert schema[0]["object"] == "customer"
        assert schema[0]["columns"][0]["name"] == "customer_id"
        assert schema[0]["columns"][0]["type"] == "integer"
        assert schema[0]["columns"][0]["nullable"] is False

    def test_auth_failed_classified(self, app, client):
        source_id = self._register(app, client)
        app.state.source_gateway.force_auth_fail(str(source_id))
        response = client.post(f"/api/v1/sources/{source_id}/test")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is False
        assert data["detail"] == "authentication_failed"
        assert data["message"]
        # Credentials never echoed in any field.
        assert "secret" not in response.text.lower()

    def test_network_unreachable_classified(self, app, client):
        source_id = self._register(app, client)
        app.state.source_gateway.force_network_unreachable(str(source_id))
        data = client.post(f"/api/v1/sources/{source_id}/test").json()
        assert data["ok"] is False
        assert data["detail"] == "network_unreachable"

    def test_database_not_found_classified(self, app, client):
        source_id = self._register(app, client)
        app.state.source_gateway.force_database_not_found(str(source_id))
        data = client.post(f"/api/v1/sources/{source_id}/test").json()
        assert data["ok"] is False
        assert data["detail"] == "database_not_found"

    def test_connection_state_updated(self, app, client, session_factory):
        from datafoundry.controlplane.db.models import ConnectionState, DataSource

        source_id = self._register(app, client)
        app.state.source_gateway.force_auth_fail(str(source_id))
        client.post(f"/api/v1/sources/{source_id}/test")
        with session_factory() as session:
            source = session.get(DataSource, uuid.UUID(source_id))
            assert source.connection_state == ConnectionState.failed
            assert source.last_test_detail == "authentication_failed"
            assert source.last_test_at is not None

    def test_unknown_source_404(self, app, client):
        response = client.post(f"/api/v1/sources/{uuid.uuid4()}/test")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith(PROBLEM_CT)


class TestListAndGetSources:
    def _register(self, app, client):
        platform_id = _seed_platform(app)
        source_id = client.post(
            "/api/v1/sources", json=_db_source(platform_id=str(platform_id))
        ).json()["source_id"]
        return source_id

    def test_list_shape(self, app, client):
        self._register(app, client)
        response = client.get("/api/v1/sources")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        item = items[0]
        assert {
            "source_id",
            "name",
            "type",
            "owner",
            "connection_state",
            "last_test_at",
        } <= set(item)
        assert item["name"] == "crm-prod"
        assert item["type"] == "postgres"
        assert item["connection_state"] == "untested"

    def test_detail_shape_secret_ref_name_only(self, app, client):
        source_id = self._register(app, client)
        response = client.get(f"/api/v1/sources/{source_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["source_id"] == source_id
        assert data["config"]["credentials"]["secretRef"] == "crm-ro-user"
        # No credential value anywhere.
        assert "password" not in response.text.lower()

    def test_get_unknown_404(self, app, client):
        response = client.get(f"/api/v1/sources/{uuid.uuid4()}")
        assert response.status_code == 404
