"""T027: Contract tests for the quarantine API (contracts/quality-api.md §4).

Covers:
- GET /datasets/{id}/quarantine: list + filters (source/pipeline/batch/reason/date).
- POST /quarantine/{id}/replay: 202 replay_run_id; 409 on retention expiry /
  not eligible.
- GET /quarantine/{id}: full entry + failure context.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

PROBLEM_CT = "application/problem+json"


def _seed_dataset(app, name="customer", owner="user@acme.com"):
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
            owner_identity=owner,
            classification=DataClassification.internal,
        )
        sess.add(ds)
        sess.commit()
        return ds.id


def _seed_entry(
    app,
    ds_id,
    *,
    batch_id=None,
    payload_ref="s3://bucket/quarantine/rec-1.parquet",
    failure_reason="duplicate customer_id",
    failed_test="uniqueness_customer_id",
    attempt_count=1,
    replay_eligible=True,
    retention_expiry=None,
    source="sap",
    pipeline_id="pipeline-1",
):
    from datafoundry.controlplane.db.models import QuarantineEntry

    with app.state.sessionmaker() as sess:
        entry = QuarantineEntry(
            dataset_id=ds_id,
            batch_id=batch_id or uuid.uuid4(),
            payload_ref=payload_ref,
            failure_reason=failure_reason,
            failed_test=failed_test,
            attempt_count=attempt_count,
            replay_eligible=replay_eligible,
            retention_expiry=retention_expiry or datetime.now(UTC) + timedelta(days=30),
            metadata_json={
                "source": source,
                "pipeline_id": pipeline_id,
                "error_details": {"code": "E_DUP"},
            },
        )
        sess.add(entry)
        sess.commit()
        return entry.id


class TestListQuarantine:
    def test_list_entries(self, app, client):
        ds_id = _seed_dataset(app)
        _seed_entry(app, ds_id)
        response = client.get(f"/api/v1/datasets/{ds_id}/quarantine")
        assert response.status_code == 200, response.text
        data = response.json()
        assert len(data["items"]) == 1
        item = data["items"][0]
        assert set(item) == {
            "entry_id",
            "batch_id",
            "payload_ref",
            "failure_reason",
            "failed_test",
            "attempt_count",
            "replay_eligible",
            "retention_expiry",
            "quarantined_at",
        }
        uuid.UUID(item["entry_id"])
        uuid.UUID(item["batch_id"])
        assert item["failure_reason"] == "duplicate customer_id"
        assert item["failed_test"] == "uniqueness_customer_id"
        assert item["attempt_count"] == 1
        assert item["replay_eligible"] is True

    def test_list_empty(self, app, client):
        ds_id = _seed_dataset(app)
        response = client.get(f"/api/v1/datasets/{ds_id}/quarantine")
        assert response.status_code == 200
        assert response.json()["items"] == []

    def test_list_unknown_dataset_404(self, app, client):
        response = client.get(f"/api/v1/datasets/{uuid.uuid4()}/quarantine")
        assert response.status_code == 404

    def test_filter_by_batch(self, app, client):
        ds_id = _seed_dataset(app)
        batch = uuid.uuid4()
        _seed_entry(app, ds_id, batch_id=batch, payload_ref="a.parquet")
        _seed_entry(app, ds_id, payload_ref="b.parquet")
        response = client.get(
            f"/api/v1/datasets/{ds_id}/quarantine", params={"batch_id": str(batch)}
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["payload_ref"] == "a.parquet"

    def test_filter_by_reason(self, app, client):
        ds_id = _seed_dataset(app)
        _seed_entry(app, ds_id, failure_reason="duplicate customer_id", payload_ref="a.parquet")
        _seed_entry(app, ds_id, failure_reason="null email", payload_ref="b.parquet")
        response = client.get(
            f"/api/v1/datasets/{ds_id}/quarantine", params={"failure_reason": "duplicate"}
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["payload_ref"] == "a.parquet"

    def test_filter_by_source(self, app, client):
        ds_id = _seed_dataset(app)
        _seed_entry(app, ds_id, source="sap", payload_ref="a.parquet")
        _seed_entry(app, ds_id, source="salesforce", payload_ref="b.parquet")
        response = client.get(f"/api/v1/datasets/{ds_id}/quarantine", params={"source": "sap"})
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["payload_ref"] == "a.parquet"

    def test_filter_by_pipeline(self, app, client):
        ds_id = _seed_dataset(app)
        _seed_entry(app, ds_id, pipeline_id="pipeline-1", payload_ref="a.parquet")
        _seed_entry(app, ds_id, pipeline_id="pipeline-2", payload_ref="b.parquet")
        response = client.get(
            f"/api/v1/datasets/{ds_id}/quarantine", params={"pipeline_id": "pipeline-2"}
        )
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 1
        assert items[0]["payload_ref"] == "b.parquet"

    def test_filter_by_date_range(self, app, client):
        ds_id = _seed_dataset(app)
        _seed_entry(app, ds_id, payload_ref="a.parquet")
        # A future-dated entry (quarantined_at defaults to now; filter by a
        # window that excludes it).
        response = client.get(
            f"/api/v1/datasets/{ds_id}/quarantine",
            params={
                "date_from": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "date_to": (datetime.now(UTC) + timedelta(days=2)).isoformat(),
            },
        )
        assert response.status_code == 200
        assert response.json()["items"] == []


class TestReplayQuarantine:
    def test_replay_returns_run_id(self, app, client):
        ds_id = _seed_dataset(app)
        entry_id = _seed_entry(app, ds_id)
        response = client.post(f"/api/v1/quarantine/{entry_id}/replay")
        assert response.status_code == 202, response.text
        data = response.json()
        assert set(data) == {"replay_run_id"}
        uuid.UUID(data["replay_run_id"])

    def test_replay_after_retention_expiry_409(self, app, client):
        ds_id = _seed_dataset(app)
        entry_id = _seed_entry(app, ds_id, retention_expiry=datetime.now(UTC) - timedelta(days=1))
        response = client.post(f"/api/v1/quarantine/{entry_id}/replay")
        assert response.status_code == 409
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["code"] == "retention_expired"

    def test_replay_not_eligible_409(self, app, client):
        ds_id = _seed_dataset(app)
        entry_id = _seed_entry(app, ds_id, replay_eligible=False)
        response = client.post(f"/api/v1/quarantine/{entry_id}/replay")
        assert response.status_code == 409
        assert response.headers["content-type"].startswith(PROBLEM_CT)
        assert response.json()["code"] == "not_eligible"

    def test_replay_unknown_entry_404(self, app, client):
        response = client.post(f"/api/v1/quarantine/{uuid.uuid4()}/replay")
        assert response.status_code == 404


class TestGetQuarantineEntry:
    def test_get_full_entry(self, app, client):
        ds_id = _seed_dataset(app)
        entry_id = _seed_entry(app, ds_id)
        response = client.get(f"/api/v1/quarantine/{entry_id}")
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["entry_id"] == str(entry_id)
        assert data["payload_ref"] == "s3://bucket/quarantine/rec-1.parquet"
        assert data["failure_reason"] == "duplicate customer_id"
        assert data["failed_test"] == "uniqueness_customer_id"
        assert data["attempt_count"] == 1
        assert data["metadata"]["source"] == "sap"
        assert data["metadata"]["pipeline_id"] == "pipeline-1"

    def test_get_unknown_entry_404(self, app, client):
        response = client.get(f"/api/v1/quarantine/{uuid.uuid4()}")
        assert response.status_code == 404
