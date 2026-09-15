"""T014: Contract tests for the gates API (contracts/quality-api.md §1).

Covers:
- POST /datasets/{id}/gates/{transition}: 201 with gate_id + config_version;
  422 all-errors (unknown category, invalid severity, no CRITICAL/ERROR test,
  secret-scan hit).
- GET /datasets/{id}/gates/{transition}: config_yaml + config_hash.
- POST /gates/{id}/run: promote/block decision + per-test results.
- GET /gates/{id}/reports/{report_id}: full report + per-test results.
"""

from __future__ import annotations

import uuid

import pyarrow as pa

PROBLEM_CT = "application/problem+json"


def _valid_gate_config(**overrides):
    config = {
        "transition": "bronze_to_silver",
        "tests": [
            {
                "name": "uniqueness_customer_id",
                "category": "uniqueness",
                "severity": "critical",
                "parameters": {"columns": ["customer_id"]},
            },
            {
                "name": "nullability_email",
                "category": "nullability",
                "severity": "error",
                "parameters": {"columns": ["email"]},
            },
        ],
    }
    config.update(overrides)
    return config


def _seed_dataset(app, name="customer"):
    from datafoundry.controlplane.db.models import (
        DataClassification,
        Dataset,
        DatasetLayer,
    )

    with app.state.sessionmaker() as sess:
        ds = Dataset(
            name=name,
            layer=DatasetLayer.silver,
            schema_definition={"customer_id": {"type": "integer", "nullable": False}},
            owner_identity="user@acme.com",
            classification=DataClassification.internal,
        )
        sess.add(ds)
        sess.commit()
        return ds.id


def _seed_table(app, dataset_id, rows):
    schema = pa.schema([pa.field("customer_id", pa.int64()), pa.field("email", pa.string())])
    app.state.quality_gateway.seed_table(str(dataset_id), "silver", schema, rows)


class TestDefineGate:
    def test_define_gate_201(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(),
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert set(data) == {"gate_id", "config_version"}
        assert data["config_version"] == 1
        uuid.UUID(data["gate_id"])

    def test_define_gate_increments_config_version(self, app, client):
        ds_id = _seed_dataset(app)
        for _ in range(2):
            response = client.post(
                f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
                json=_valid_gate_config(),
            )
            assert response.status_code == 201
        assert response.json()["config_version"] == 2

    def test_unknown_category_422(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(
                tests=[
                    {
                        "name": "t",
                        "category": "not_a_category",
                        "severity": "critical",
                        "parameters": {},
                    }
                ]
            ),
        )
        assert response.status_code == 422
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["errors"]

    def test_invalid_severity_422(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(
                tests=[
                    {
                        "name": "t",
                        "category": "uniqueness",
                        "severity": "fatal",
                        "parameters": {"columns": ["x"]},
                    }
                ]
            ),
        )
        assert response.status_code == 422

    def test_no_critical_or_error_test_422(self, app, client):
        """Fail-closed: a gate with no CRITICAL/ERROR test is rejected (FR-002)."""
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(
                tests=[
                    {
                        "name": "t",
                        "category": "uniqueness",
                        "severity": "warning",
                        "parameters": {"columns": ["x"]},
                    }
                ]
            ),
        )
        assert response.status_code == 422
        assert any("critical" in e["message"] for e in response.json()["errors"])

    def test_secret_scan_hit_422(self, app, client):
        """A gate config containing a secret is rejected (SC-007)."""
        ds_id = _seed_dataset(app)
        response = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(
                tests=[
                    {
                        "name": "t",
                        "category": "uniqueness",
                        "severity": "critical",
                        "parameters": {"columns": ["x"], "token": "AKIA1234567890ABCDEF"},
                    }
                ]
            ),
        )
        assert response.status_code == 422
        assert any("secret" in e["message"] for e in response.json()["errors"])

    def test_unknown_dataset_404(self, app, client):
        response = client.post(
            f"/api/v1/datasets/{uuid.uuid4()}/gates/bronze_to_silver",
            json=_valid_gate_config(),
        )
        assert response.status_code == 404


class TestExportGate:
    def test_export_gate_config(self, app, client):
        ds_id = _seed_dataset(app)
        define = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(),
        ).json()
        response = client.get(f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {
            "gate_id",
            "transition",
            "config_version",
            "config_yaml",
            "config_hash",
        }
        assert data["gate_id"] == define["gate_id"]
        assert data["config_version"] == 1
        assert data["config_hash"].startswith("sha256:")
        assert len(data["config_hash"]) == len("sha256:") + 64

    def test_export_missing_gate_404(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.get(f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver")
        assert response.status_code == 404


class TestRunGate:
    def _define_and_seed(self, app, client, rows):
        ds_id = _seed_dataset(app)
        gate_id = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(),
        ).json()["gate_id"]
        _seed_table(app, ds_id, rows)
        return ds_id, gate_id

    def test_run_block_on_duplicates(self, app, client):
        _ds_id, gate_id = self._define_and_seed(
            app,
            client,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 1, "email": "b@x.com"},
                {"customer_id": 2, "email": "c@x.com"},
            ],
        )
        response = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["decision"] == "block"
        assert data["overall_status"] == "failed"
        assert data["tests_failed"] == 1
        assert data["tests_run"] == 2
        assert data["config_version"] == 1
        # The failing uniqueness test is listed with its failed-record count.
        uniqueness = next(r for r in data["results"] if r["test"] == "uniqueness_customer_id")
        assert uniqueness["status"] == "failed"
        assert uniqueness["failed_record_count"] == 1
        assert uniqueness["measured_value"]["duplicates"] == 1

    def test_run_promote_on_clean_data(self, app, client):
        _ds_id, gate_id = self._define_and_seed(
            app,
            client,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 2, "email": "b@x.com"},
            ],
        )
        response = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["decision"] == "promote"
        assert data["overall_status"] == "passed"
        assert data["tests_failed"] == 0

    def test_run_unknown_gate_404(self, app, client):
        response = client.post(
            f"/api/v1/gates/{uuid.uuid4()}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        )
        assert response.status_code == 404


class TestGateReport:
    def test_report_detail(self, app, client):
        ds_id = _seed_dataset(app)
        gate_id = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(),
        ).json()["gate_id"]
        _seed_table(
            app,
            ds_id,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 1, "email": "b@x.com"},
            ],
        )
        run = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        ).json()
        response = client.get(f"/api/v1/gates/{gate_id}/reports/{run['report_id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["report_id"] == run["report_id"]
        assert data["decision"] == "block"
        assert data["tests_run"] == 2
        assert len(data["results"]) == 2
        # Drill-down: each result carries test_id, severity, status, count.
        for item in data["results"]:
            assert item["test_id"]
            assert item["severity"] in {"critical", "error"}
            assert item["status"] in {"passed", "failed"}

    def test_report_unknown_404(self, app, client):
        ds_id = _seed_dataset(app)
        gate_id = client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(),
        ).json()["gate_id"]
        response = client.get(f"/api/v1/gates/{gate_id}/reports/{uuid.uuid4()}")
        assert response.status_code == 404


class TestEnvSeverityOverride:
    """T033: per-environment severity via ``environment_overrides`` (FR-005).

    The same test is WARNING in Development and CRITICAL in Production; with
    identical failing data the Development run continues (promote) while the
    Production run blocks. The override round-trips through config export.
    """

    def _define(self, app, client):
        ds_id = _seed_dataset(app)
        config = {
            "transition": "bronze_to_silver",
            "environment_overrides": {
                "production": {"uniqueness_customer_id": "critical"},
            },
            "tests": [
                {
                    "name": "uniqueness_customer_id",
                    "category": "uniqueness",
                    "severity": "warning",
                    "parameters": {"columns": ["customer_id"]},
                },
                {
                    "name": "nullability_email",
                    "category": "nullability",
                    "severity": "critical",
                    "parameters": {"columns": ["email"]},
                },
            ],
        }
        define = client.post(f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver", json=config)
        assert define.status_code == 201, define.text
        return ds_id, define.json()["gate_id"]

    def _seed_duplicates(self, app, ds_id):
        _seed_table(
            app,
            ds_id,
            [
                {"customer_id": 1, "email": "a@x.com"},
                {"customer_id": 1, "email": "b@x.com"},
                {"customer_id": 2, "email": "c@x.com"},
            ],
        )

    def test_development_continues_production_blocks(self, app, client):
        ds_id, gate_id = self._define(app, client)
        self._seed_duplicates(app, ds_id)

        dev = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "development",
            },
        )
        assert dev.status_code == 200, dev.text
        assert dev.json()["decision"] == "promote"
        assert dev.json()["overall_status"] == "warning"
        assert dev.json()["tests_failed"] == 1

        prod = client.post(
            f"/api/v1/gates/{gate_id}/run",
            json={
                "run_id": str(uuid.uuid4()),
                "batch_id": str(uuid.uuid4()),
                "environment": "production",
            },
        )
        assert prod.status_code == 200, prod.text
        assert prod.json()["decision"] == "block"
        assert prod.json()["overall_status"] == "failed"
        assert prod.json()["tests_failed"] == 1

    def test_override_visible_in_config_export(self, app, client):
        ds_id, _gate_id = self._define(app, client)
        response = client.get(f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver")
        assert response.status_code == 200
        assert "environment_overrides" in response.json()["config_yaml"]
        assert "production" in response.json()["config_yaml"]
        assert "uniqueness_customer_id" in response.json()["config_yaml"]


class TestListTests:
    def test_list_tests(self, app, client):
        ds_id = _seed_dataset(app)
        client.post(
            f"/api/v1/datasets/{ds_id}/gates/bronze_to_silver",
            json=_valid_gate_config(),
        )
        response = client.get(f"/api/v1/datasets/{ds_id}/tests")
        assert response.status_code == 200
        data = response.json()
        assert len(data["items"]) == 2
        names = {item["name"] for item in data["items"]}
        assert names == {"uniqueness_customer_id", "nullability_email"}
        for item in data["items"]:
            assert item["test_id"]
            assert item["category"]
            assert item["severity"]
            assert "parameters" in item

    def test_list_tests_unknown_dataset_404(self, app, client):
        response = client.get(f"/api/v1/datasets/{uuid.uuid4()}/tests")
        assert response.status_code == 404
