# Phase 0 Research: Self-Service Data Ingestion

**Feature**: 002-data-ingestion | **Date**: 2026-09-14

All Technical Context unknowns resolved. Format: Decision / Rationale / Alternatives considered.

---

## R-01: Ingestion framework — Airbyte vs. in-process connectors

**Decision**: For MVP, build a **thin, in-process connector framework** inside the existing control plane (registry-driven `Connector` ABC with `discover_schema`, `test_connection`, `extract` operations) covering exactly the MVP source set: PostgreSQL, SQL Server, and CSV/JSON/Parquet from S3/GCS. **Do not deploy Airbyte** in MVP.

**Rationale**:
- The MVP source set is small (2 databases + 3 file formats over 2 object stores); a generic connector platform adds a second stateful service (Airbyte server + its own Postgres + temporal/workflow infra) whose operational burden and 30-minute-deploy budget clash with the self-contained promise.
- BRD §11 mandates an *evaluation*, not a mandate: "evaluate Airbyte rather than automatically developing bespoke connectors", "custom code only where an existing connector does not adequately satisfy requirements". This research records the evaluation and the deferral.
- Portability (Principle I) and simplicity/cost (Governance) favour reusing the control plane's worker/DB/secret-scan/audit rather than integrating Airbyte's separate config store and credential model, which would duplicate the secret-handling guarantees (SC-007) already built in feature 001.
- The connector registry mirrors the capability-registry pattern (Principle I, FR-015): adding a source type = one new connector module + registration entry, no core change.

**Alternatives considered**:
- *Airbyte (self-hosted/OSS)*: excellent connector coverage and incremental/CDC, but a heavyweight second runtime; its own credential store would need to be reconciled with the platform's `secretRef` model; CDC is explicitly out of MVP scope, removing Airbyte's strongest differentiator for this phase.
- *Cloud-native (AWS DMS/Glue, GCP Datastream/Data Fusion)*: breaks portability (Principle I) and SC-008 (same config both clouds); rejected outright.
- *dlt / Meltano*: dlt is Python-idiomatic and would reduce code, but introduces an opinionated external dependency for only 2 DB + 3 file types; the in-house connectors keep full control over batch metadata (FR-008) and quarantine routing (FR-006).
- **Revisit Airbyte at Phase 2** when CDC/streaming/SaaS connectors enter scope (per BRD "evaluated rather than mandated prematurely").

## R-02: Database source connectivity & schema discovery

**Decision**: Use **SQLAlchemy Core** as the single abstraction over database sources. PostgreSQL via `psycopg` (async-capable) and SQL Server via `pymssql` (pure-python, no ODBC driver install). Schema discovery = SQLAlchemy `inspector` (tables, columns, types, nullability, PKs). Extraction streams rows server-side; incremental runs add `WHERE cursor_col > :last_high_watermark ORDER BY cursor_col` with the high-watermark persisted per source object in the control-plane DB.

**Rationale**:
- SQLAlchemy is already a dependency (feature 001) and gives a uniform dialect layer; no new query-engine dependency.
- `pymssql` avoids the freetds/ODBC system-driver installation that `pyodbc` requires, keeping the Docker image self-contained (30-min onboarding budget, SC-001).
- Server-side streaming + ordered incremental cursors are the standard, correct mechanism for the "zero duplicates across repeated incremental runs" guarantee (SC-005, FR-003).

**Alternatives considered**:
- *`pyodbc` + msodbcsql*: standard for SQL Server but needs a system driver; heavier image.
- *Per-source vendor SDKs (psycopg2, adodbapi)*: more code paths for no capability gain over SQLAlchemy dialects.
- *JDBC bridge*: adds a JVM; rejected for simplicity.

## R-03: File/object-storage parsing & record counting

**Decision**: **PyArrow** (`pyarrow`) for reading CSV, JSON, and Parquet from object storage, streaming through the existing `CloudGateway` (S3/GCS) rather than direct SDK calls. Record counts, checksums (SHA-256), and per-file metadata come from the same read pass. Duplicate-file detection = checksum comparison against previously ingested checksums for that source location (FR-007).

**Rationale**:
- PyArrow handles all three formats uniformly, preserves types for contract inference, and is already the de-facto Iceberg/Parquet ecosystem standard (feature 003 alignment).
- Routing all object reads through `CloudGateway` keeps S3/GCS parity structural (Principle I, SC-008) and lets tests swap in the simulated inventory.

**Alternatives considered**:
- *pandas read_*: fine for CSV but heavier and non-streaming for large files.
- *Python csv/json stdlib*: no Parquet support, no type inference, slower.
- *DuckDB*: excellent, but introduces a query engine prematurely (feature 006 semantic layer may revisit).

## R-04: Scheduling model

**Decision**: An **in-process scheduler loop** inside the control plane (a background thread ticker that queries for due pipelines and dispatches runs through the existing worker/dispatcher hook) rather than a standalone scheduler service. Schedules stored per pipeline as a cron-like or interval spec (every 15m / hourly / daily), evaluated in the platform's configured timezone.

**Rationale**:
- MVP scale is tens of pipelines; a distributed scheduler (Airflow/Prefect/Celery) is over-provisioning and would reintroduce the chicken-and-egg orchestration bootstrap.
- Reuses the feature 001 dispatcher (background thread → `process_run`) so manual and scheduled runs share one execution path (FR-011).
- Feature 001's `orchestration` capability (Airflow) is available to customers *inside* the platform for their own DAGs; the control plane's own scheduling need not depend on it.

**Alternatives considered**:
- *APScheduler*: adds a dependency for cron parsing we can implement in a dozen lines; rejected for simplicity.
- *Airflow/Prefect/Celery*: second scheduler runtime + broker; overkill at MVP scale.
- *Cloud scheduler (EventBridge/Cloud Scheduler)*: breaks portability.

## R-05: Bronze landing layout & batch atomicity

**Decision**: Land batches into the platform Bronze prefix using the BRD layout `bronze/<source_object>/source=<source_name>/ingestion_date=<YYYY-MM-DD>/<batch_id>/` (source-aligned, partitioned by ingestion date — FR-018). Each run writes to a **staging path** then atomically "commits" by a final rename/manifest write; a failed mid-run never presents a torn batch as complete (FR-015, edge cases). Batch metadata (source system, table/file, timestamp, batch id, pipeline id, record count, status) written as a `_batch_metadata.json` alongside the data and mirrored to the control-plane DB (FR-008, SC-003).

**Rationale**:
- Staging-then-commit gives the "no torn batch" guarantee structurally (mirrors feature 001's per-run workspace isolation philosophy).
- Partitioning by ingestion_date satisfies FR-018 and replayability/auditability (SC-003 traceability from Bronze to source).

**Alternatives considered**:
- *Write-in-place with a completion marker*: simpler but a crash mid-write leaves partially-visible data.
- *Iceberg tables directly in Bronze*: feature 003 scope (Bronze is raw/immutable, Iceberg is a Silver/Gold table-format decision); keep Bronze as raw partitioned objects for MVP.

## R-06: Incremental dedup & high-watermark persistence

**Decision**: Persist a **per-source-object high-watermark** (last successfully ingested cursor value) in the control-plane DB, updated only on a fully successful, validated batch. Incremental runs read `> watermark` and are therefore idempotent on retry (FR-003, FR-014, SC-005). A retry re-reads from the *uncommitted* watermark so already-ingested records are not duplicated.

**Rationale**: The DB is the source of truth (same as feature 001 R-01); advancing the watermark only on commit makes retries naturally non-duplicating without source-side change tracking (CDC is out of scope).

**Alternatives considered**:
- *Source-side timestamps/CDC*: CDC deferred to Phase 2 per BRD.
- *Dedup via checksums in Bronze*: expensive full-scan; watermark is the standard cursor approach.

## R-07: Validation & contract compatibility

**Decision**: Two-phase ingestion-level validation, mirroring feature 001's shift-left approach:
1. **Pre-landing** (during/at extraction): file validation (exists, readable, format, encoding, checksum — FR-006) and schema/contract compatibility against the recorded `SourceContract` (FR-009). Violations classified breaking / non-breaking / warning (FR-010, constitution IV).
2. **Post-landing reconciliation**: source record count vs. ingested record count (FR-009). A failing *critical* check marks the batch `INGESTED` but **not** `INGESTION_VALIDATED`, blocking promotion and raising an alert (FR-020).

Where no contract exists, the **first** successful ingestion infers a contract from the observed schema and marks it **pending approval** (never auto-approved — constitution V) (FR-010, US3-AC3).

**Rationale**: Directly implements the constitutional "detect as early as possible" and the INGESTED → INGESTION_VALIDATED gate; the classification taxonomy (breaking/non-breaking/warning) is specified in the constitution and feature 004 builds the full severity model on top.

**Alternatives considered**:
- *Great Expectations (GX)*: strong but feature 004's concern (full gate engine); ingestion only needs schema-compat + count reconciliation, kept in-house for now.
- *JSON Schema validation only*: doesn't cover type-change classification semantics.

## R-08: Quarantine routing

**Decision**: Invalid files and records are written to `quarantine/<source_object>/<batch_id>/` in the platform bucket with a `_quarantine_metadata.json` (original reference, failure reason, failed check, timestamp, pipeline id, batch id, source — FR-006, BRD §23M). A parallel `QuarantineRecord` row is persisted for query/filter (feature 004 adds replay; this feature only records). Valid files in a partially-invalid batch are still ingested (US2-AC2 partial success).

**Rationale**: "Quarantine rather than propagate" is a core correctness guarantee; keeping the quarantine *payload* in object storage (not the DB) preserves the original record while the DB row gives searchable metadata. Replay is feature 004's scope (the spec's quarantine hand-off).

**Alternatives considered**:
- *DB-stored payloads*: bloats the control-plane DB and complicates large-file quarantine.
- *Silent drop*: explicitly forbidden.

## R-09: Secrets & credentials for sources

**Decision**: Source credentials are stored as **`secretRef`** names resolved at run time from the platform's secret manager (feature 001 `secrets` capability), never inline in the ingestion config, export, log, or UI (FR-005, SC-007). The existing secret-scan pass runs on every ingestion-config write/export and on all run/batch/error payloads.

**Rationale**: Reuses feature 001's structural secret guarantee (R-09) — SC-007 is enforced by architecture, not discipline.

**Alternatives considered**:
- *Inline encrypted credentials in config*: rejected in feature 001 R-09 for the same reasons.

## R-10: Run serialisation & concurrency

**Decision**: Mirror feature 001's one-active-run invariant: a partial unique index on `IngestionRun WHERE status IN ('queued','running','paused')` per pipeline, plus a `SELECT ... FOR UPDATE` row lock on the pipeline. Runs against the same source/destination are serialised; a file arriving mid-run is picked up by the next run (FR-012, edge cases).

**Rationale**: Same mechanism, same guarantees, same test harness as feature 001 (R-12).

---

## Resolution Summary

| Unknown from Technical Context | Resolved by |
|---|---|
| Airbyte evaluation / framework choice | R-01 (defer Airbyte; in-process connectors) |
| DB connectivity & schema discovery | R-02 |
| File parsing & record counting | R-03 |
| Scheduling | R-04 |
| Bronze layout & batch atomicity | R-05 |
| Incremental dedup & watermark | R-06 |
| Validation & contract compatibility | R-07 |
| Quarantine routing | R-08 |
| Source secrets | R-09 |
| Run serialisation | R-10 |

No NEEDS CLARIFICATION items remain. Proceed to Phase 1 design artifacts.
