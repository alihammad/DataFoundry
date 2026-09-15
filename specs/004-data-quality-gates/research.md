# Phase 0 Research: Shift-Left Data Quality Gates

**Feature**: 004-data-quality-gates | **Date**: 2026-09-15

All Technical Context unknowns resolved. Format: Decision / Rationale / Alternatives considered.

---

## R-01: Quality framework — Great Expectations / Soda / dbt / custom

**Decision**: For MVP, build a **thin, in-process quality engine** inside the existing control plane: a `Test` ABC with `evaluate` per category, a gate composition layer, and a deterministic decision function. **Do not deploy Great Expectations, Soda, or dbt** as the gate engine in MVP.

**Rationale**:
- The MVP needs the 17 standard categories with severity + per-environment override, fail-closed semantics, and deep integration with the control plane's run/audit/secret-scan/override model. A third-party framework would need to be wrapped to expose exactly these semantics, and its own config store/credential model would duplicate the platform's guarantees (FR-018 GitOps, FR-011 override audit).
- BRD §45 mandates an *evaluation*, not a mandate: "evaluate Great Expectations / Soda / dbt rather than automatically developing bespoke quality tooling". This research records the evaluation and the deferral.
- Portability (Principle I) and simplicity/cost (Governance) favour reusing the control plane's worker/DB/audit rather than integrating a separate quality runtime.
- The test-category registry mirrors the capability-registry and feature 002 connector-registry patterns (Principle I, FR-015 spirit): adding a test category = one module + registration entry, no core change.

**Alternatives considered**:
- *Great Expectations (GX)*: the most complete expectation library, but heavyweight (its own DataContext, stores, checkpoint runtime) and its expectation model maps awkwardly onto the platform's severity/per-environment gate semantics; strong candidate to revisit if the category set grows beyond MVP.
- *Soda Core*: lightweight and SQL-first, good for reconciliation/volume; but its checks model is less expressive for per-environment severity and its scan lifecycle would need re-plumbing into the control-plane run model.
- *dbt tests*: excellent for transformation-adjacent tests and GitOps-native, but assumes a dbt project per dataset and pulls the transformation engine (feature 003's concern) into the quality layer prematurely.
- **Revisit at Phase 2** when statistical/AI anomaly detection and AI-assisted test generation enter scope (per BRD "evaluated rather than mandated prematurely").

## R-02: Test evaluation engine — PyArrow + DuckDB

**Decision**: Evaluate record-level tests (schema, type, nullability, uniqueness, completeness, validity, referential, contract, transformation, security) with **PyArrow** over the zone's Parquet/CSV/JSON; evaluate SQL-based tests (reconciliation, distribution, business rule, volume, freshness, statistical) with **DuckDB** over Silver/Gold datasets. Both read through the existing `CloudGateway` (S3/GCS).

**Rationale**:
- PyArrow is already the de-facto Iceberg/Parquet ecosystem standard (feature 003 alignment) and handles all three formats uniformly with type preservation.
- DuckDB is the constitution-mandated lightweight query engine for Silver/Gold (constitution "DuckDB SHALL be evaluated for lightweight/analyst querying"); using it for SQL tests keeps one query engine across quality and consumption (feature 006 alignment).
- Routing all reads through `CloudGateway` keeps S3/GCS parity structural (Principle I, SC-008) and lets tests swap in the simulated inventory.

**Alternatives considered**:
- *pandas*: fine for small data but non-streaming and heavier for large datasets.
- *SQLAlchemy over the source DB*: tests must run against the *landed zone data, not the source; rejected.
- *Spark*: over-provisioned for MVP dataset scale (tens of datasets, medium size).

## R-03: Gate decision & fail-closed semantics

**Decision**: A gate is a set of tests bound to a layer transition for a dataset. Decision function: if any CRITICAL or ERROR test fails — **or cannot execute** (infrastructure error) — the gate is **BLOCK**; otherwise **PROMOTE**. WARNING failures continue with notification; INFORMATIONAL records only. The gate configuration version active when the batch started is recorded with results (edge case: config change mid-flight).

**Rationale**:
- Fail-closed is a constitutional requirement (FR-002, constitution III): an unexecuted critical test must block, and the report must distinguish "test failed" from "test could not run".
- Recording the gate config version per run makes results reproducible and auditable (FR-013, edge case).

**Alternatives considered**:
- *Fail-open on infrastructure error*: explicitly forbidden by FR-002.
- *Majority/weighted decision*: a single critical failure must block regardless of other passes (US4-AC2); weighted scoring is reserved for the quality *score*, not the gate decision.

## R-04: Contract validation & inference

**Decision**: Contracts are validated at ingestion against the observed schema. Violations classified **breaking** (type change, column removal — blocks promotion), **non-breaking** (additive nullable column — allowed, recorded), or **warning** (recorded, notified). Where no explicit contract exists, the **first** successful ingestion infers a contract from the observed schema and marks it **pending approval**; the owner approves, edits, or rejects it (never auto-approved — constitution V, FR-007).

**Rationale**:
- Directly implements the constitutional "detect as early as possible" and the breaking/non-breaking/warning taxonomy (constitution IV, FR-006).
- Inference is deterministic (observed schema → pending approval), satisfying constitution V's "deterministic validation before execution" and "never auto-approved".

**Alternatives considered**:
- *JSON Schema validation only*: doesn't cover type-change classification semantics.
- *Auto-approve inferred contracts*: explicitly forbidden by constitution V.

## R-05: Quarantine with replay & retention

**Decision**: Quarantine entries persist the original payload reference, failure reason, failed test, timestamp, pipeline id, batch id, source, and error details (FR-008). Replay re-enters the records at the appropriate stage after root-cause resolution; replay must not duplicate successfully processed records (FR-009). Entries follow a configurable retention policy; replay after expiry is refused explicitly (FR-010). Repeated replay failures increment an attempt count and escalate to the owner beyond a threshold (FR-009).

**Rationale**:
- "Quarantine rather than propagate" is a core correctness guarantee (constitution III); keeping the payload in object storage (not the DB) preserves the original record while the DB row gives searchable metadata (feature 002 R-08 pattern).
- Replay idempotency + attempt escalation operationalise recoverability without silent drops.

**Alternatives considered**:
- *DB-stored payloads*: bloats the control-plane DB and complicates large-file quarantine (feature 002 R-08).
- *Unbounded quarantine*: retention policy required by FR-010.

## R-06: Override model

**Decision**: An override is a recorded bypass of a **specific blocked run** requiring authorisation, reason, expiry, user identity, timestamp, and impact assessment (FR-011). Incomplete overrides rejected; overrides expire automatically and remain permanently in the dataset's audit history (FR-012). An override applies only to the granted run — reprocessing re-evaluates the gate (edge case).

**Rationale**:
- Directly implements constitution III's override requirements and FR-011/FR-012; the "specific run only" scoping prevents a granted override from silently covering future runs.

**Alternatives considered**:
- *Dataset-level standing override*: violates FR-012 and the edge case "override applies only to the specific blocked run".
- *Silent bypass flag*: explicitly forbidden (FR-011).

## R-07: Quality score & observability

**Decision**: Every test execution is recorded as metadata (dataset, pipeline, run id, tests run/passed/warned/failed, overall status, failed record counts, gate config version — FR-013). A deterministic quality score per dataset is computed from recent gate results (FR-014), with drill-down from a summary into an individual run, failing test, failed records, and quarantine entries (FR-015). Alerts fire on gate failures, contract violations, and warning-threshold breaches through the platform's notification channels (FR-016).

**Rationale**:
- Observability by default is a constitutional requirement (constitution Development Workflow); the score formula is deterministic and documented per spec Assumptions.

**Alternatives considered**:
- *Ad-hoc scoring*: spec Assumptions require a documented, deterministic formula.
- *No alerting*: FR-016 mandates alerts on failures.

## R-08: Version control & GitOps for quality definitions

**Decision**: Test definitions, gate configurations, and contracts are version-controlled and flow through the GitOps change workflow (FR-018), reusing the feature 001 `config/gitops.py pattern. Test-first development is supported: contracts and tests can be defined before the transformation exists, and a pipeline can be deployed with gates already bound (FR-020).

**Rationale**: GitOps is a constitutional requirement (constitution Development Workflow); reusing the existing gitops module keeps one change workflow across configs.

**Alternatives considered**:
- *DB-only definitions*: violates FR-018 and the constitution's GitOps mandate.