# Quickstart: Validating Self-Service Data Ingestion

**Feature**: 002-data-ingestion | **Date**: 2026-09-14

Runnable validation scenarios proving the feature works end-to-end. References: [contracts/ingestion-api.md](./contracts/ingestion-api.md), [contracts/source-config-schema.md](./contracts/source-config-schema.md), [contracts/source-contract-schema.md](./contracts/source-contract-schema.md), [data-model.md](./data-model.md).

---

## Prerequisites

- Feature 001 control plane running (see `specs/001-one-click-platform-deployment/quickstart.md`) — the API, a deployed platform with `ingestion`/`storage_zones`/`catalog`/`secrets` capabilities, and the `datafoundry` CLI in the venv.
- Source connectivity is **simulated** for offline validation (no docker/terraform/real database required): `DF_SIMULATE_CLOUD=1` (default) uses the in-memory `SimulatedSourceGateway`.

## Setup (local development)

```bash
cd control-plane && source .venv/bin/activate
uv run alembic upgrade head            # applies the feature 002 migration
uv run uvicorn datafoundry.controlplane.api.app:app --reload --port 8000

# sanity
curl -s http://localhost:8000/healthz
# Expected: {"status":"ok","version":"..."}
```

---

## Scenario 1: Register a source and test connectivity (US1, FR-004)

```bash
datafoundry source add crm-prod --type postgres \
  --host crm.internal --database crm --secret-ref crm-ro-user
datafoundry source test crm-prod
```

**Expected**: `ok: true` within one minute; discovered schema lists `customer` and `orders` tables with columns/types/nullability (US1-AC1).

Negative test (US1-AC4):

```bash
datafoundry source test crm-prod --force-auth-fail   # simulated
# Expected: ok: false, detail: authentication_failed, actionable message; no config saved
```

---

## Scenario 2: Configure ingestion and run it (US1, FR-002, FR-003, FR-018)

```bash
datafoundry source configure crm-prod --config configs/crm-to-bronze.yaml
# config selects customer (incremental, cursor updated_at) + orders (full),
# schedule "every 15 minutes", target bronze.
```

**Expected**: `201` with `config_id`, `version`, and a **created `pipeline_id`** (no custom code — FR-002). Then:

```bash
datafoundry ingest run --pipeline <pipeline_id>
```

**Expected**:
1. `202` with `run_id`; run reaches `succeeded`.
2. Batches land in Bronze `bronze/customer/source=crm-prod/ingestion_date=<date>/<batch_id>/` and `bronze/orders/...` with `_batch_metadata.json` (source system, table, timestamp, batch id, pipeline id, record count, status — FR-008).
3. First run: contracts inferred and `approval_status: pending` (US3-AC3).

---

## Scenario 3: Incremental runs produce zero duplicates (FR-003, SC-005)

Trigger a second run after the source advances:

```bash
datafoundry ingest run --pipeline <pipeline_id>   # second run
```

**Expected**: only records `> last high-watermark` are ingested (R-06); `record_count` reflects only the delta; no duplicate records in Bronze for the same source rows (verified against the simulated source's ≥1M-row test dataset).

---

## Scenario 4: File ingestion, validation & quarantine (US2, FR-006, FR-007)

```bash
datafoundry source add events-drop --type object_storage --location s3://acme-landing/events --format parquet
datafoundry source configure events-drop --config configs/events-to-bronze.yaml
datafoundry ingest run --pipeline <events_pipeline_id>
```

**Expected**:
1. Valid Parquet files land in Bronze with file-level metadata (name, size, checksum, timestamp — US2-AC1).
2. A deliberately corrupted file is routed to `quarantine/events/<batch_id>/` with failure reason + `_quarantine_metadata.json` (US2-AC2); valid files still ingested; run `outcome: partial`.
3. Delivering the same file twice (identical checksum) → duplicate detected, recorded, not double-loaded (US2-AC3, FR-007).

---

## Scenario 5: Breaking schema change blocks promotion (US3, FR-009, FR-010)

After approving the `customer` contract, mutate the simulated source so `customer_id` becomes `string`:

```bash
datafoundry ingest run --pipeline <pipeline_id>
```

**Expected**:
1. Contract check classifies `integer → string` as `breaking` (FR-010).
2. Batch status `ingested` but **not** `ingestion_validated`; promotion blocked (FR-009).
3. Alert raised to owner naming the column and change (US3-AC2, FR-020); record-count reconciliation reports any source-vs-ingested difference (US3-AC4).

---

## Scenario 6: Operational control — pause, resume, retry (US4, FR-014)

```bash
datafoundry pipeline pause <pipeline_id>
# schedule elapses -> no run started, state visible as paused (US4-AC3)
datafoundry pipeline resume <pipeline_id>
# force a failure, then:
datafoundry ingest retry --run <failed_run_id>
```

**Expected**: retry re-processes only what's needed, no duplicate already-ingested records (US4-AC2, R-06); history and logs reflect every action accurately (FR-013).

---

## Test suite map

| Layer | Coverage |
|---|---|
| unit | connectors (discover/test/extract), contract classification, file validation, incremental watermark/dedup |
| contract | ingestion-api, source-config-schema, source-contract-schema |
| integration | wizard → run → validate → quarantine flows against `SimulatedSourceGateway` |
| manual E2E | live sandbox PostgreSQL + S3/GCS source (gated) |
