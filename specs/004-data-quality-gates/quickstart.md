# Quickstart: Validating Shift-Left Data Quality Gates

**Feature**: 004-data-quality-gates | **Date**: 2026-09-15

Runnable validation scenarios proving the feature works end-to-end. References: [contracts/quality-api.md](./contracts/quality-api.md), [contracts/gate-config-schema.md](./contracts/gate-config-schema.md), [contracts/contract-schema.md](./contracts/contract-schema.md), [data-model.md](./data-model.md).

---

## Prerequisites

- Feature 001 control plane running (see `specs/001-one-click-platform-deployment/quickstart.md`) — the API, a deployed platform with `storage_zones`/`catalog`/`secrets` capabilities, and the `datafoundry` CLI in the venv.
- Feature 002 ingestion hand-off states (`INGESTED → INGESTION_VALIDATED`) and quarantine routing available.
- Test evaluation is **simulated** for offline validation (no docker/terraform/real database required): `DF_SIMULATE_CLOUD=1` (default) uses the in-memory `SimulatedQualityGateway` with record fixtures.

## Setup (local development)

```bash
cd control-plane && source .venv/bin/activate
uv run alembic upgrade head            # applies the feature 004 migration
uv run uvicorn datafoundry.controlplane.api.app:app --reload --port 8000

# sanity
curl -s http://localhost:8000/healthz
# Expected: {"status":"ok","version":"..."}
```

---

## Scenario 1: Gate blocks bad data at a layer transition (US1, FR-001, FR-002)

Define a gate on the Bronze→Silver transition with a critical uniqueness test:

```bash
datafoundry gate set <dataset_id> bronze_to_silver --config configs/silver-gate.yaml
# config: uniqueness_customer_id (critical), nullability_email (error),
#         freshness_check (warning), volume_check (critical)
```

**Expected**: `201` with `gate_id` + `config_version: 1`. A gate with no CRITICAL/ERROR test is rejected `422` (fail-closed, FR-002).

Run the gate against a batch with duplicate `customer_id` values:

```bash
datafoundry gate run <gate_id> --run <run_id> --batch <batch_id> --env production
```

**Expected**:
1. `decision: block`, `overall_status: failed`, `tests_failed: 1` (the critical uniqueness test).
2. Promotion does **not** occur; the dataset stays at the failed layer with a BLOCKED indication (US1-AC2, US4-AC1).
3. Gate report lists every test with pass/fail/warning status and the failed-record count (US1-AC3).

---

## Scenario 2: Contract validation & classification (US2, FR-006, FR-007)

Register an explicit contract:

```bash
datafoundry contract register <dataset_id> --schema configs/customer-contract.json
```

**Expected**: `201`, `origin: explicit`, approved immediately (US2-AC1).

Feed a batch that changes a column type (`integer`→`string`):

```bash
datafoundry contract validate <dataset_id> --batch <batch_id>
```

**Expected**: violation classified `breaking`; promotion blocked; owner notified with the exact change (US2-AC2, SC-007).

Inference path (US2-AC3/AC4):

```bash
datafoundry contract infer <dataset_id>   # first successful ingestion
# Expected: origin: inferred, approval_status: pending (never auto-approved)
datafoundry contract approve <contract_id>
# Expected: approval_status: approved; now gates promotion
```

---

## Scenario 3: Quarantine with replay (US3, FR-008, FR-009, FR-010)

Ingest a batch with known bad records:

```bash
datafoundry quarantine list <dataset_id>
```

**Expected**: every failed record appears with `payload_ref`, `failure_reason`, `failed_test`, `batch_id`, `quarantined_at` (FR-008, US3-AC1). Filter by source/pipeline/batch/reason/date (US3-AC3).

Fix the root cause, then replay:

```bash
datafoundry quarantine replay <entry_id>
```

**Expected**: `202` with `replay_run_id`; records re-enter processing; a successful replay removes them from the active queue with **no duplicates** (FR-009, US3-AC2). Replay after `retention_expiry` is refused `409` (FR-010).

---

## Scenario 4: Override of a blocked gate (US5, FR-011, FR-012)

Block a gate (Scenario 1), then grant an override:

```bash
datafoundry override grant <report_id> \
  --identity user@acme.com \
  --reason "Known upstream incident; data verified manually" \
  --expiry 2026-09-16T00:00:00Z \
  --impact "3 downstream dashboards affected for <24h"
```

**Expected**: `201`, `status: active`; promotion proceeds; override permanently in the dataset's audit history (US5-AC1, FR-012).

Negative tests:
- Incomplete override (missing `impact_assessment`) → `422` (FR-011).
- Caller without override authority → `403`, attempt recorded (US5-AC2).
- After `expiry`, the gate fails again → promotion blocked anew; old override grants no permission (US5-AC3).

---

## Scenario 5: Quality score & observability (US6, FR-013, FR-014, FR-015)

Run the pipeline several times with varying outcomes, then:

```bash
datafoundry quality get <dataset_id>
datafoundry quality history <dataset_id>
```

**Expected**: current score (0–100, deterministic formula) + per-run history with `decision`, `overall_status`, test counts, and `config_version` (US6-AC1, FR-013/FR-014). Drill into a failed run:

```bash
datafoundry gate report <report_id>
```

**Expected**: reaches the specific failing test, its failed records, and related quarantine entries (US6-AC2, FR-015).