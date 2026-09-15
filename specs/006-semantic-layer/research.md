# Phase 0 Research: Semantic Layer

**Feature**: 006-semantic-layer | **Date**: 2026-09-15

All Technical Context unknowns resolved. Format: Decision / Rationale / Alternatives considered.

---

## R-01: Semantic-layer technology — Cube / dbt Semantic Layer / custom

**Decision**: For MVP, build a **thin, in-process semantic engine** inside the existing control plane: a declarative `SemanticModel` (metrics, dimensions, measures, relationships) validated by Pydantic, computed with **DuckDB** over Gold/Silver datasets, and published through the GitOps workflow. **Do not deploy Cube or dbt Semantic Layer** as the semantic runtime in MVP.

**Rationale**:
- The MVP needs declarative definitions, GitOps publication with semantic tests, access-policy enforcement from feature 005, freshness/quality surfacing, and deep integration with the control plane's run/audit/secret-scan model. A third-party semantic layer would need to be wrapped to expose exactly these semantics, and its own config store/credential model would duplicate the platform's guarantees (FR-003 GitOps, FR-007 access, FR-008 freshness).
- BRD §45 mandates an *evaluation*, not a mandate: "evaluate Cube / dbt Semantic Layer rather than automatically developing bespoke semantic tooling". This research records the evaluation and the deferral.
- Portability (Principle I) and simplicity/cost (Governance) favour reusing the control plane's worker/DB/audit and the constitution-mandated DuckDB query engine rather than integrating a separate semantic runtime.
- The metric/dimension/measure/relationship registry mirrors the capability-registry and feature 002 connector-registry patterns (Principle I): adding a metric = one declarative definition, no core change.

**Alternatives considered**:
- *Cube*: the most complete semantic layer (metrics, dimensions, caching, multi-tenant), but heavyweight (its own data model, cache store, API server) and its model maps awkwardly onto the platform's GitOps publication + access-policy + freshness-surfacing semantics; strong candidate to revisit if the metric set grows beyond MVP.
- *dbt Semantic Layer*: excellent for transformation-adjacent metrics and GitOps-native, but assumes a dbt project per dataset and pulls the transformation engine (feature 003's concern) into the semantic layer prematurely; its MetricFlow model is less expressive for the platform's access/quality surfacing.
- **Revisit at Phase 2** when BI-tool connectors (Looker/Power BI) and natural-language querying enter scope (per BRD "evaluated rather than mandated prematurely").

## R-02: Metric computation engine — DuckDB

**Decision**: Compute metrics with **DuckDB** over Gold/Silver datasets read through the existing `CloudGateway` (S3/GCS). A metric is a declarative definition (measure + aggregation + optional filter + dimensions) compiled to a DuckDB query; the same definition produces identical results on both clouds (FR-013, SC-008).

**Rationale**:
- DuckDB is the constitution-mandated lightweight query engine for Silver/Gold (constitution "DuckDB SHALL be evaluated for lightweight/analyst querying"); using it for metric computation keeps one query engine across quality (feature 004) and semantic consumption.
- Routing all reads through `CloudGateway` keeps S3/GCS parity structural (Principle I, SC-008) and lets the engine swap in the simulated inventory.
- DuckDB handles the aggregation/filter/join semantics metrics need (sum, count, avg, group-by dimensions, relationship joins) without a separate OLAP server.

**Alternatives considered**:
- *Cube pre-aggregations*: powerful but adds a caching/OLAP runtime; deferred (R-01).
- *Spark*: over-provisioned for MVP dataset scale (tens of datasets, medium size).
- *Direct SQL over the source DB*: metrics must run against the *landed Gold/Silver zone data, not the source; rejected.

## R-03: Semantic model & GitOps lifecycle

**Decision**: A `SemanticModel` is the versioned collection of metrics, dimensions, measures, and relationships for a domain — the unit of publication. Definitions are declarative YAML validated by a strict Pydantic schema (reusing the feature 004 `quality_schema.py` pattern). Changes flow through the GitOps workflow (propose → validate → approve → publish, FR-003), reusing the feature 001 `config/gitops.py` pattern. Changes are classified breaking/non-breaking (FR-005); breaking changes require explicit approval and notify registered consumers.

**Rationale**:
- GitOps is a constitutional requirement (constitution Development Workflow); reusing the existing gitops module keeps one change workflow across configs.
- The strict-schema + secret-scan pattern from feature 004 gives all-errors-at-once validation and secret-scan on every write (SC-007).

**Alternatives considered**:
- *DB-only definitions*: violates FR-003 and the constitution's GitOps mandate.
- *Auto-publish on change*: violates FR-005 (breaking changes require approval).

## R-04: Semantic tests

**Decision**: Semantic tests are bound to a definition and run at publish time AND on schedule against production data (FR-014). Categories: **calculation** (metric produces expected result on reference data), **reconciliation** (aggregation reconciles with the underlying dataset), **relationship** (dimension relationships hold, no fan-out/double-counting), **filter** (filters behave as defined). A failing semantic test blocks publication (FR-004); a scheduled test that fails on production data flags drift (FR-014).

**Rationale**:
- Directly implements FR-004 (publication requires passing semantic tests) and FR-014 (tests run on schedule against production data).
- The test-category registry mirrors the feature 004 quality-test registry pattern (Principle I): adding a semantic test category = one module + registration entry.

**Alternatives considered**:
- *Publish-time tests only*: misses drift detection on production data (FR-014).
- *No relationship/fan-out test*: the spec edge case explicitly requires detecting aggregation anomalies before publication (SC-007).

## R-05: Access enforcement

**Decision**: Semantic queries enforce feature 005's access policies: role-based visibility of metrics, column-level protection preserved in results (masked/tokenised per policy), and row-level restrictions applied (FR-007). A metric over a RESTRICTED dataset is only queryable by roles authorised for that classification. Protected column values never appear in semantic query output without authorised detokenisation (SC-005).

**Rationale**:
- The semantic layer must not become a security bypass around feature 005's protection policies (spec US3 rationale). It *enforces* policies, never defines them (spec Assumptions).
- Reusing feature 005's access module keeps one enforcement path across the platform.

**Alternatives considered**:
- *Semantic-layer-owned access model*: violates the spec Assumption that access policies are owned by feature 005.

## R-06: Freshness & quality surfacing

**Decision**: Semantic query results report the data freshness and quality state of underlying datasets (FR-008). Data known to have failed its quality gate (feature 004) is blocked or explicitly flagged per policy — never silently served as current. The definition version used is recorded with every result (FR-012, SC-006).

**Rationale**:
- Directly implements FR-008 (never silently serve stale numbers as current) and the spec edge case (metric's underlying dataset fails its quality gate or is stale → surface freshness/quality state or refuse).
- Recording the definition version per result makes past reports reproducible (FR-012, SC-006).

**Alternatives considered**:
- *Silently serve stale data*: explicitly forbidden by FR-008 and the spec edge case.

## R-07: Discovery & catalog

**Decision**: Semantic definitions are searchable through the catalog (FR-011), with certified (published) definitions distinguished from drafts. A business user searches a business term and finds the certified metric with definition, owner, quality score, freshness, lineage, and consuming teams (US4-AC1). Draft definitions are hidden from general users or clearly marked as draft (US4-AC2).

**Rationale**:
- Directly implements FR-011 and US4; the semantic layer supplies the semantic metadata, while catalog registration/search is a platform capability (feature 003 metadata + feature 007 UI, spec Assumptions).

**Alternatives considered**:
- *No catalog integration*: violates FR-011 and US4.

## R-08: Consumer registration, notification & deprecation

**Decision**: Consumers register which metrics they consume (FR-005, FR-010). Breaking changes and deprecations notify registered consumers. Deprecation marks a definition deprecated with a successor reference where applicable; queries return a deprecation notice with results, or are refused after the deprecation period (FR-010).

**Rationale**:
- Directly implements FR-005 (breaking changes notify registered consumers) and FR-010 (deprecation with consumer notification, successor reference, time-bounded continued availability).
- The consumer-registration record mirrors the feature 004 override-audit pattern: permanent, auditable.

**Alternatives considered**:
- *No consumer registration*: violates FR-005/FR-010 notification requirements.
- *Immediate deprecation refusal*: violates FR-010's time-bounded continued availability.