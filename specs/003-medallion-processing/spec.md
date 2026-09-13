# Feature Specification: Medallion Architecture Processing

**Feature Branch**: `feature/003-medallion-processing`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: "...process it using Medallion architecture..." — this feature covers the Bronze, Silver, and Gold layers: storage zones, transformation between layers, explicit promotion states gated by quality validation, and consumption readiness.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Bronze layer preserves raw source data (Priority: P1)

Ingested data lands in the Bronze layer exactly as received from the source: immutable, source-aligned, replayable, and auditable. A data engineer can see, for any Bronze dataset, which source it came from, when it was ingested, how many records it contains, and its ingestion status. Bronze data can be replayed to reprocess downstream layers without re-extracting from the source.

**Why this priority**: Bronze is the foundation of the Medallion architecture and the platform's audit/replay guarantee. Nothing downstream exists without it.

**Independent Test**: Can be tested by ingesting a known dataset, verifying Bronze content matches the source byte-for-byte in semantics (records, values), verifying immutability (an update attempt is rejected or creates a new version rather than altering history), and replaying the batch into a fresh Silver run.

**Acceptance Scenarios**:

1. **Given** a validated ingestion batch, **When** it lands in Bronze, **Then** the data is stored in the standard source-aligned layout partitioned by ingestion date, with full batch metadata attached.
2. **Given** data already written to Bronze, **When** any process attempts to modify or delete it outside the retention policy, **Then** the attempt is rejected and recorded.
3. **Given** a Bronze batch, **When** an engineer triggers a replay, **Then** downstream Silver processing re-runs from that Bronze data without contacting the source system.

---

### User Story 2 - Silver layer delivers cleaned, conformed data (Priority: P1)

A data engineer defines Silver transformations for a dataset: cleansing, type conversion, standardisation, deduplication, schema enforcement, and handling of malformed records. When the transformation runs against validated Bronze data, the output lands in Silver only after passing Silver-layer quality checks. Malformed records are routed to quarantine, not silently dropped or propagated. Analysts can consume Silver directly.

**Why this priority**: Silver is where raw data becomes trustworthy. Equal priority with Bronze — the pair forms the minimum viable Medallion flow.

**Independent Test**: Can be tested by running a Silver transformation over a Bronze dataset containing known duplicates, type errors, and nulls, then verifying: clean records in Silver, bad records in quarantine with reasons, and the quality check results recorded.

**Acceptance Scenarios**:

1. **Given** INGESTION_VALIDATED Bronze data, **When** the Silver transformation runs and Silver quality checks pass, **Then** the dataset reaches SILVER_VALIDATED state and is visible to analysts.
2. **Given** records failing cleansing rules, **When** the transformation runs, **Then** failed records are quarantined with the failure reason and the batch reports both processed and quarantined counts.
3. **Given** a Silver dataset, **When** the same source data is reprocessed, **Then** deduplication ensures each business entity appears once per the configured keys.
4. **Given** a transformation definition change, **When** the change goes through the version-control workflow and is deployed, **Then** subsequent runs use the new logic and prior runs remain traceable to the version that produced them.

---

### User Story 3 - Gold layer delivers business-ready datasets (Priority: P2)

An analytics engineer defines Gold datasets (e.g. customer 360, sales performance) built from validated Silver data. Each Gold dataset has a clear owner, documented business definition, quality rules, and business metadata. Gold datasets are discoverable in the catalog, version controlled, and optimised for consumption. Gold promotion requires passing the strongest validation, including business reconciliation against Silver.

**Why this priority**: Gold delivers business value but depends on functioning Bronze and Silver flows; it is the second wave of the MVP.

**Independent Test**: Can be tested by defining a Gold aggregate dataset over a Silver dataset with known totals, running the build, and verifying reconciliation (Gold totals match Silver within documented transformation rules), ownership metadata, and catalog discoverability.

**Acceptance Scenarios**:

1. **Given** SILVER_VALIDATED inputs, **When** the Gold build runs and Gold quality and reconciliation checks pass, **Then** the dataset reaches GOLD_VALIDATED and then CONSUMABLE state.
2. **Given** a Gold dataset, **When** a user views it in the catalog, **Then** the user sees owner, business definition, quality score, refresh frequency, and lineage to Silver sources.
3. **Given** a Gold reconciliation failure (aggregates do not match Silver within tolerance), **When** the build completes, **Then** promotion to CONSUMABLE is blocked and the discrepancy is reported.

---

### User Story 4 - Explicit promotion states with gate enforcement (Priority: P2)

Every dataset moves through explicit states: INGESTED → INGESTION_VALIDATED → BRONZE → BRONZE_VALIDATED → SILVER → SILVER_VALIDATED → GOLD → GOLD_VALIDATED → CONSUMABLE. A dataset only transitions when the relevant quality gate passes. Any state, and the reason for it, is visible to engineers. A failed gate blocks promotion automatically; an authorised override (with reason, expiry, identity, timestamp, impact assessment) is the only path past a failed gate.

**Why this priority**: The state machine is the enforcement backbone of "quality before promotion" — the platform's zero-contamination guarantee. Depends on gates defined in feature 004.

**Independent Test**: Can be tested by attempting to promote a dataset with a failed critical gate and verifying promotion is refused; then applying a recorded override and verifying promotion proceeds and the override is auditable.

**Acceptance Scenarios**:

1. **Given** a dataset whose current-layer gate failed on a critical check, **When** any process attempts promotion, **Then** promotion is refused and the dataset state remains at the failed layer with a BLOCKED indication.
2. **Given** a blocked dataset, **When** an authorised user records an override with reason, expiry, and impact assessment, **Then** promotion proceeds, and the override appears in the dataset's audit history.
3. **Given** any dataset, **When** a user queries its status, **Then** the user sees the current promotion state, the gate results that produced it, and the timestamp of the last transition.

---

### User Story 5 - Analysts query Silver and Gold directly (Priority: P3)

An analyst browses the catalog, picks a Silver or Gold dataset, and queries it directly with SQL — including lightweight local querying without loading data into a warehouse — and downloads results. The analyst sees the schema, quality score, and freshness before querying.

**Why this priority**: Consumption proves the Medallion delivers value, but depends on the layers existing first. The BRD explicitly requires direct analyst access to Silver/Gold.

**Independent Test**: Can be tested by querying a Silver and a Gold dataset through the platform's query experience, verifying results match the stored data, and downloading a result set.

**Acceptance Scenarios**:

1. **Given** a CONSUMABLE Gold dataset, **When** an authorised analyst runs a SQL query, **Then** results return correctly and reflect the dataset's current version.
2. **Given** a dataset the analyst is not authorised for, **When** the analyst attempts to query it, **Then** access is denied per the platform's access-control policies.
3. **Given** a query result, **When** the analyst downloads it, **Then** the download respects column-level protection policies (protected columns remain masked/tokenised per policy).

---

### Edge Cases

- What happens when a Silver transformation runs against Bronze data that was later replayed/corrected? Reprocessing must produce a new, consistent Silver version; consumers see either the old or new version atomically, never a torn mix.
- What happens when a Gold build's Silver input is blocked or stale? The Gold build must refuse to run on non-SILVER_VALIDATED inputs and report the dependency state.
- What happens when a transformation produces zero records from a non-empty input? Treated as a suspicious outcome: flagged by volume checks before promotion, not silently published as an empty dataset.
- What happens when schema evolution occurs upstream (new column in Bronze)? Silver transformations must tolerate additive changes per the contract classification rules; breaking changes block promotion.
- What happens when two engineers deploy conflicting transformation versions for the same dataset? Version control serialises changes; the deployed version is unambiguous and every run records which version produced it.
- What happens when quarantine volume for a batch exceeds the records that passed? The batch is flagged as predominantly failed; promotion is blocked regardless of individual gate scores.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST organise analytical data into three layers: Bronze (raw, source-aligned, immutable), Silver (cleaned, conformed), Gold (business-ready), with the standard storage layout per layer.
- **FR-002**: Bronze data MUST be immutable in practice: modification or deletion outside an approved retention policy MUST be rejected and recorded.
- **FR-003**: Bronze datasets MUST be replayable: downstream layers MUST be reprocessable from Bronze without re-extracting from source systems.
- **FR-004**: Every Bronze dataset MUST carry: source system, source object, ingestion timestamp, batch id, pipeline id, record count, and ingestion status.
- **FR-005**: System MUST support declarative, version-controlled transformation definitions for Bronze→Silver and Silver→Gold, including cleansing, type conversion, standardisation, deduplication, schema enforcement, and aggregation.
- **FR-006**: Transformations MUST route failing records to quarantine with failure reasons; failed records MUST NOT be silently dropped or propagated.
- **FR-007**: System MUST enforce the promotion state machine INGESTED → INGESTION_VALIDATED → BRONZE → BRONZE_VALIDATED → SILVER → SILVER_VALIDATED → GOLD → GOLD_VALIDATED → CONSUMABLE; transitions MUST occur only when the corresponding quality gate passes.
- **FR-008**: Promotion past a failed gate MUST require a recorded override containing authorisation, reason, expiry, user identity, timestamp, and impact assessment; silent bypass MUST be impossible.
- **FR-009**: Gold datasets MUST require owner, documented business definition, quality rules, and business metadata before reaching CONSUMABLE state.
- **FR-010**: Gold builds MUST include reconciliation against Silver inputs (e.g. aggregate totals match within documented transformation tolerance); reconciliation failure MUST block promotion.
- **FR-011**: Gold builds MUST refuse to run on inputs that are not SILVER_VALIDATED.
- **FR-012**: Dataset writes MUST be atomic per version: consumers MUST see either the previous or the new version, never a partial mix; concurrent writers MUST NOT corrupt a dataset.
- **FR-013**: System MUST support schema evolution for additive changes without breaking downstream transformations; breaking changes MUST follow the contract classification and block promotion.
- **FR-014**: Every dataset MUST be registered in the catalog with: owner, steward, domain, description, classification, quality score, lineage (upstream and downstream), and refresh metadata.
- **FR-015**: Lineage MUST be maintained end-to-end: source → Bronze → Silver → Gold → consumers, navigable in both directions.
- **FR-016**: Authorised analysts MUST be able to query Silver and Gold datasets directly with SQL, including lightweight querying without a warehouse load, and download results subject to protection policies.
- **FR-017**: Every transformation run MUST record the transformation version, input dataset versions, output version, gate results, and quarantined record counts.
- **FR-018**: The layer model, transformation definitions, promotion states, and metadata MUST be cloud-independent: identical logical behaviour on all supported clouds.
- **FR-019**: System MUST use an open lakehouse table format supporting ACID transactions, schema evolution, time travel/versioning, and multi-engine access, per the constitutional standard.
- **FR-020**: Zero-record outputs from non-empty inputs MUST be flagged as suspicious and blocked from promotion pending review.

### Key Entities

- **Dataset**: A logical table/file collection in a layer. Attributes: name, layer, schema, owner, steward, domain, classification, quality score, promotion state, version history, lineage links, refresh metadata.
- **Layer**: Bronze, Silver, or Gold; defines the data's maturity and the gate requirements for entry and exit.
- **Transformation**: A version-controlled definition converting input dataset(s) to an output dataset. Attributes: id, version, source layer, target layer, logic definition, tests/gates bound to it, owner.
- **Promotion State**: The dataset's position in the state machine, with the gate results and timestamps that produced each transition, plus any overrides applied.
- **Dataset Version**: An immutable snapshot of a dataset produced by a run; supports time travel and atomic consumer reads.
- **Lineage Link**: A directed relationship between datasets (or source→dataset) recording derivation, transformation version, and timestamps.
- **Quarantined Record**: Rejected record with original payload reference, failure reason, failed check, batch id, and replay eligibility.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero knowingly failed quality-gated datasets are promoted to downstream layers (constitution's zero-contamination metric), verified by audit of all promotions over a quarter.
- **SC-002**: 100% of production datasets exist in the Medallion layers with complete catalog metadata (owner, classification, quality score, lineage, refresh data).
- **SC-003**: Any Bronze batch can be replayed to regenerate Silver and Gold without source-system access, verified on at least one full end-to-end dataset.
- **SC-004**: Analysts query Silver/Gold directly and receive correct results; a representative analyst query completes in interactive time (seconds for medium datasets) without a warehouse load.
- **SC-005**: 100% of promotions past a failed gate carry a complete, auditable override record.
- **SC-006**: End-to-end lineage (source to consumer) is navigable for 100% of Gold datasets.
- **SC-007**: The same transformation definitions and dataset metadata run unchanged on both supported clouds, verified by a parity deployment.

## Assumptions

- Quality gate definitions, test categories, severity levels, and the quarantine facility are specified in feature 004 (data-quality-gates); this feature consumes them as the promotion conditions.
- The open table format is Apache Iceberg per the constitution ("SHALL be the evaluated table format"); lightweight analyst querying uses DuckDB per the constitutional evaluation mandate. FR-019 states required capabilities, not products.
- Transformation tooling (dbt / SQL / Spark) is a planning-time decision per BRD section 45; this spec requires declarative, version-controlled transformations without mandating the engine.
- Streaming ingestion into Bronze is out of MVP scope (batch only); the layer model must not preclude streaming later.
- Data warehouse integration and API consumption of Gold are out of scope for this feature (BRD Phase 2); direct SQL querying and downloads are in scope.
- Retention policies for Bronze immutability exceptions are organisation-defined; the platform enforces whatever policy is configured.
