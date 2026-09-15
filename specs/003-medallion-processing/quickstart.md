# Quickstart: Validating Medallion Architecture Processing

**Feature**: 003-medallion-processing | **Date**: 2026-09-15

Runnable validation scenarios proving the feature works end-to-end. References: [contracts/processing-api.md](./contracts/processing-api.md), [contracts/transformation-schema.md](./contracts/transformation-schema.md), [contracts/dataset-schema.md](./contracts/dataset-schema.md), [data-model.md](./data-model.md).

---

## Prerequisites

- Feature 001 control plane running (see `specs/001-one-click-platform-deployment/quickstart.md`) — the API, a deployed platform with `storage_zones`/`catalog`/`secrets` capabilities, and the `datafoundry` CLI in the venv.
- Feature 002 ingestion hand-off states (`INGESTED → INGESTION_VALIDATED`) and Bronze zone data available.
- Feature 004 quality gates available (gate decisions drive promotion).
- Processing is **simulated** for offline validation (no docker/terraform/real database required): `DF_SIMULATE_CLOUD=1` (default) uses the in-memory `SimulatedProcessingGateway` with record fixtures + Iceberg-in-memory.

## Setup (local development)

```bash
cd control-plane && source .venv/bin/activate
uv run alembic upgrade head            # applies the feature 003 migration
uv run uvicorn datafoundry.controlplane.api.app:app --reload --port 8000

# sanity
curl -s http://localhost:8000/healthz
# Expected: {"status":"ok","version":"..."}
```

---

## Scenario 1: Bronze is immutable and replayable (US1, FR-002, FR-003)

Register a Bronze dataset from an ingested batch:

```bash
datafoundry dataset register <platform_id> --name customer_bronze --layer bronze \
  --schema configs/customer-schema.json --owner user@acme.com --classification internal
```

**Expected**: `201` with `dataset_id`; the dataset carries source system, source object, ingestion timestamp, batch id, pipeline id, record count, and ingestion status (FR-004).

Attempt to modify Bronze data outside the retention policy:

```bash
datafoundry dataset mutate <dataset_id> --delete-records
```

**Expected**: the attempt is rejected and recorded (FR-002, US1-AC2).

Replay Bronze into a fresh Silver run without contacting the source:

```bash
datafoundry transform run <silver_transform_id> --input <bronze_dataset_id>
```

**Expected**: Silver reprocesses from Bronze data; no source-system access (FR-003, US1-AC3).

---

## Scenario 2: Silver delivers cleaned, conformed data (US2, FR-005, FR-006)

Define a Silver transformation (cleansing, type conversion, dedup, schema enforcement):

```bash
datafoundry transform define --config configs/customer-silver-transform.json
```

**Expected**: `201` with `transformation_id` + `version: 1`.

Run it against a Bronze dataset with known duplicates, type errors, and nulls:

```bash
datafoundry transform run <transform_id> --input <bronze_dataset_id>
```

**Expected**:
1. Clean records land in Silver; the dataset reaches `SILVER_VALIDATED` and is visible to analysts (US2-AC1).
2. Records failing cleansing rules are quarantined with the failure reason; the batch reports both processed and quarantined counts (US2-AC2, FR-006).
3. Reprocessing the same source data deduplicates per `dedup_keys`: each business entity appears once (US2-AC3).
4. A transformation definition change goes through the version-control workflow; subsequent runs use the new logic, prior runs remain traceable to the version that produced them (US2-AC4, FR-017).

---

## Scenario 3: Gold delivers business-ready datasets (US3, FR-009, FR-010, FR-011)

Define a Gold aggregate dataset over a Silver dataset with known totals:

```bash
datafoundry dataset register <platform_id> --name customer_360_gold --layer gold \
  --schema configs/gold-schema.json --owner user@acme.com --classification internal \
  --description "Customer 360" --refresh '{"schedule":"daily"}' --quality-score 95
datafoundry transform define --config configs/customer-360-gold-transform.json
```

**Expected**: `201` for both; the Gold dataset carries owner, business definition, quality rules, business metadata, and lineage to Silver sources (US3-AC2, FR-009).

Run the Gold build:

```bash
datafoundry transform run <gold_transform_id> --input <silver_dataset_id>
```

**Expected**: on passing Gold quality + reconciliation checks, the dataset reaches `GOLD_VALIDATED` then `CONSUMABLE` (US3-AC1, FR-010). A reconciliation failure (aggregates do not match Silver within tolerance) blocks promotion to CONSUMABLE and reports the discrepancy (US3-AC3, FR-010). A Gold build on a non-SILVER_VALIDATED input is refused (FR-011).

---

## Scenario 4: Promotion states with gate enforcement (US4, FR-007, FR-008)

Query a dataset's promotion status:

```bash
datafoundry promote status <dataset_id>
```

**Expected**: current promotion state, the gate results that produced it, and the last transition timestamp (US4-AC3).

Attempt to promote a dataset whose current-layer gate failed on a critical check:

```bash
datafoundry promote run <dataset_id>
```

**Expected**: promotion refused; the dataset stays at the failed layer with a BLOCKED indication (US4-AC1, FR-007).

Grant an override:

```bash
datafoundry promote override <dataset_id> \
  --identity user@acme.com \
  --reason "Known upstream incident; data verified manually" \
  --expiry 2026-09-16T00:00:00Z \
  --impact "3 downstream dashboards affected for <24h"
```

**Expected**: `201`, promotion proceeds, override appears in the dataset's audit history (US4-AC2, FR-008). Incomplete override → `422`; unauthorised caller → `403` + recorded (US5-AC2).

---

## Scenario 5: Analysts query Silver and Gold directly (US5, FR-016)

Query a CONSUMABLE Gold dataset:

```bash
datafoundry query run <gold_dataset_id> --sql "SELECT customer_id, SUM(amount) AS total FROM customer_360_gold GROUP BY customer_id"
```

**Expected**: results return correctly and reflect the dataset's current version (US5-AC1, FR-016). Querying an unauthorised dataset → `403` (US5-AC2).

Download a result set:

```bash
datafoundry query download <gold_dataset_id> --sql "SELECT * FROM customer_360_gold" --format csv
```

**Expected**: download respects column-level protection policies; protected columns remain masked/tokenised per policy (US5-AC3, FR-016).