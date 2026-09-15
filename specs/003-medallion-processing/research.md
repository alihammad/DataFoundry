# Phase 0 Research: Medallion Architecture Processing

**Feature**: 003-medallion-processing | **Date**: 2026-09-15

All Technical Context unknowns resolved. Format: Decision / Rationale / Alternatives considered.

---

## R-01: Transformation tooling — dbt / SQL / Spark / custom

**Decision**: For MVP, build a **thin, in-process transformation engine** inside the existing control plane: a `Transformation` ABC with `apply` per type (Bronze→Silver: cleanse/type-convert/dedup/schema-enforce; Silver→Gold: aggregate/reconcile), executed with **PyArrow** for record-level work and **DuckDB** for SQL-based aggregation. **Do not deploy dbt, Spark, or a separate transformation runtime** in MVP.

**Rationale**:
- The MVP transformation set is small (cleansing, type conversion, standardisation, dedup, schema enforcement, aggregation); a generic transformation platform adds a second runtime whose operational burden clashes with the self-contained promise.
- BRD §45 mandates an *evaluation*, not a mandate: "evaluate dbt / SQL / Spark rather than automatically developing bespoke transformation tooling". This research records the evaluation and the deferral.
- Portability (Principle I) and simplicity/cost (Governance) favour reusing the control plane's worker/DB/audit rather than integrating a separate transformation runtime.
- The transformation-type registry mirrors the capability-registry and feature 002 connector-registry patterns (Principle I, FR-015 spirit): adding a transformation type = one module + registration entry, no core change.

**Alternatives considered**:
- *dbt*: excellent for SQL-first transformations and GitOps-native, but assumes a dbt project per dataset and pulls a separate orchestration/state model into the control plane; strong candidate to revisit if the transformation set grows beyond MVP.
- *Spark*: over-provisioned for MVP dataset scale (tens of datasets, medium size); heavy runtime.
- *Cloud-native (AWS Glue, GCP Dataflow)*: breaks portability (Principle I) and SC-007 (same config both clouds); rejected outright.
- **Revisit at Phase 2** when streaming/CDC and large-scale transformations enter scope (per BRD "evaluated rather than mandated prematurely").

## R-02: Table format — Apache Iceberg via PyIceberg

**Decision**: Silver and Gold datasets are written as **Apache Iceberg** tables (FR-019) using **PyIceberg** (`pyiceberg`), the constitution-mandated evaluated table format. Iceberg provides ACID transactions, schema evolution, time travel/versioning, and multi-engine access (FR-019). Bronze stays raw partitioned objects (feature 002 R-05) — Iceberg is a Silver/Gold decision.

**Rationale**:
- The constitution mandates Iceberg as the evaluated table format; FR-019 requires ACID, schema evolution, time travel, and multi-engine access — Iceberg provides all four.
- PyIceberg is the Python-native client, keeping the control plane self-contained (no JVM/Spark dependency).
- Atomic per-version writes (FR-012) map directly to Iceberg's snapshot/commit model: consumers see either the previous or new snapshot, never a torn mix.

**Alternatives considered**:
- *Delta Lake*: strong but not the constitution-mandated format; adds a different ecosystem.
- *Hudi*: similar; not mandated.
- *Plain Parquet objects*: no ACID/schema-evolution/time-travel; fails FR-019.

## R-03: Analyst querying — DuckDB

**Decision**: Authorised analysts query Silver/Gold datasets directly with **DuckDB** (FR-016), reading the Iceberg tables in place — lightweight, no warehouse load. Downloads respect column-level protection policies (masking/tokenisation per policy, FR-016, US5-AC3).

**Rationale**:
- The constitution mandates DuckDB be evaluated for lightweight/analyst querying of Silver/Gold; it reads Iceberg tables directly and returns results in interactive time for medium datasets (SC-004).
- Reuses the same engine as feature 004's SQL-based tests (one query engine across quality and consumption).

**Alternatives considered**:
- *Warehouse load (Redshift/BigQuery)*: out of MVP scope per spec Assumptions (BRD Phase 2); DuckDB gives interactive querying without a warehouse.
- *Spark SQL*: over-provisioned; DuckDB is lighter and constitution-aligned.

## R-04: Promotion state machine & gate enforcement

**Decision**: Enforce the full state machine `INGESTED → INGESTION_VALIDATED → BRONZE → BRONZE_VALIDATED → SILVER → SILVER_VALIDATED → GOLD → GOLD_VALIDATED → CONSUMABLE` (FR-007). A dataset transitions only when the relevant quality gate passes; the gate decision comes from feature 004. A failed gate blocks promotion automatically and marks the dataset BLOCKED at the failed layer. An override (authorisation, reason, expiry, identity, timestamp, impact assessment) is the only path past a failed gate, applies only to the specific blocked run, and is permanently audited (FR-008).

**Rationale**:
- Directly implements constitution III's state machine and FR-007/FR-008; the "specific run only" override scoping prevents a granted override from silently covering future runs.
- The gate decision is owned by feature 004; this feature consumes it as the promotion condition (spec Assumptions).

**Alternatives considered**:
- *Implicit promotion on write*: violates FR-007 (gates must gate).
- *Standing override*: violates FR-008 (override applies only to the granted run).

## R-05: Bronze immutability & replay

**Decision**: Bronze data is immutable in practice (FR-002): modification or deletion outside an approved retention policy is rejected and recorded. Bronze datasets are replayable (FR-003): downstream Silver/Gold can be reprocessed from Bronze without re-extracting from source systems. Reprocessing produces a new, consistent Silver/Gold version; consumers see either the old or new version atomically (FR-012, edge case).

**Rationale**:
- Bronze immutability is the audit/replay guarantee (US1); replay from Bronze (not source) satisfies FR-003 and SC-003.
- Atomic per-version writes (Iceberg snapshots, R-02) give the "never a torn mix" guarantee.

**Alternatives considered**:
- *Mutable Bronze*: violates FR-002 and the audit/replay guarantee.
- *Re-extract from source on replay*: violates FR-003 (replay must not contact the source).

## R-06: Deduplication & schema evolution

**Decision**: Silver transformations deduplicate per configured business keys (FR-005, US2-AC3): each business entity appears once per the configured keys. Schema evolution is tolerated for additive changes (new nullable column) per the contract classification rules; breaking changes (type change, column removal) block promotion (FR-013). A transformation producing zero records from a non-empty input is flagged suspicious and blocked from promotion pending review (FR-020).

**Rationale**:
- Dedup per business keys is the standard correctness mechanism for "each business entity appears once" (US2-AC3).
- Additive-tolerant/breaking-block schema evolution matches constitution IV and feature 004's contract classification.
- Zero-record-from-non-empty is a suspicious outcome that must not be silently published (FR-020, edge case).

**Alternatives considered**:
- *No dedup*: violates US2-AC3.
- *Silent zero-record publish*: violates FR-020.

## R-07: Gold metadata, reconciliation & lineage

**Decision**: Gold datasets require owner, documented business definition, quality rules, and business metadata before reaching CONSUMABLE (FR-009). Gold builds include reconciliation against Silver inputs (aggregate totals match within documented transformation tolerance); reconciliation failure blocks promotion (FR-010). Gold builds refuse to run on inputs that are not SILVER_VALIDATED (FR-011). Every dataset is registered in the catalog with owner, steward, domain, description, classification, quality score, lineage, and refresh metadata (FR-014); lineage is maintained end-to-end source → Bronze → Silver → Gold → consumers, navigable both directions (FR-015).

**Rationale**:
- Gold is business-ready only with ownership + reconciliation (FR-009, FR-010); refusing non-SILVER_VALIDATED inputs prevents building on bad data (FR-011).
- Catalog registration + lineage satisfy constitution's metadata & lineage mandate and FR-014/FR-015.

**Alternatives considered**:
- *Gold without metadata*: violates FR-009 and SC-002.
- *No reconciliation*: violates FR-010 and US3-AC3.

## R-08: Version control & GitOps for transformations

**Decision**: Transformation definitions are version-controlled and flow through the GitOps change workflow (FR-005, FR-017), reusing the feature 001 `config/gitops.py` pattern. Every transformation run records the transformation version, input dataset versions, output version, gate results, and quarantined record counts (FR-017). Prior runs remain traceable to the version that produced them (US2-AC4).

**Rationale**: GitOps is a constitutional requirement (constitution Development Workflow); reusing the existing gitops module keeps one change workflow across configs. Version traceability per run satisfies FR-017 and US2-AC4.

**Alternatives considered**:
- *DB-only transformation definitions*: violates FR-005/FR-017 and the constitution's GitOps mandate.