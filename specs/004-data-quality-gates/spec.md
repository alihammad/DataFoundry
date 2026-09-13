# Feature Specification: Shift-Left Data Quality Gates

**Feature Branch**: `feature/004-data-quality-gates`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: "...process it using Medallion architecture..." — this feature covers the quality control system: shift-left testing at every lifecycle stage, data contracts, test categories and severity levels, per-layer quality gates, quarantine with replay, test observability, and controlled manual override.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Quality gates block bad data at every layer transition (Priority: P1)

Each Medallion layer transition has a configurable quality gate composed of tests. When a dataset is processed, its gate runs automatically. If all critical tests pass, promotion proceeds. If a critical test fails, promotion is blocked automatically, the responsible people are alerted, and the failed data never reaches the next layer. Engineers see a gate report: each test, its result, and the overall promote/block decision.

**Why this priority**: "Quality before promotion" is the platform's core correctness guarantee and the zero-contamination success metric. No other quality capability matters if gates do not enforce.

**Independent Test**: Can be tested by configuring a gate on a Silver transition, feeding data that violates a critical rule, and verifying promotion is blocked, the alert fires, and the gate report shows the failing test and affected record count.

**Acceptance Scenarios**:

1. **Given** a dataset with a configured gate, **When** processing completes and all critical tests pass, **Then** the gate decision is PROMOTE and the dataset advances its promotion state.
2. **Given** a dataset whose gate has a failing CRITICAL test, **When** processing completes, **Then** the gate decision is BLOCK, promotion does not occur, and the pipeline owner is alerted with the failure detail.
3. **Given** a blocked gate, **When** an engineer opens the gate report, **Then** the report lists every test with pass/fail/warning status, the failed records count, and drill-down into the failing records or their identifiers.

---

### User Story 2 - Data contracts validated at ingestion (Priority: P1)

Producers and consumers agree a data contract per dataset: schema, types, nullability, and expectations. The platform validates incoming data against the contract during ingestion. Violations are classified as breaking (blocks promotion), non-breaking (allowed, recorded), or warning (recorded, notified). Where no explicit contract exists, the platform infers one from observed data, subject to owner approval.

**Why this priority**: Contracts are the earliest (shift-left-most) defence and a constitutional requirement. Equal priority with gates — contracts feed gate decisions.

**Independent Test**: Can be tested by registering a contract, then ingesting batches that: match it (passes), add a nullable column (warning), change a column type (breaking, blocked), and remove a column (breaking, blocked) — verifying each classification and outcome.

**Acceptance Scenarios**:

1. **Given** a registered contract, **When** incoming data matches it, **Then** the contract check passes and ingestion proceeds normally.
2. **Given** a source that changed a column type incompatibly, **When** the next batch arrives, **Then** the violation is classified breaking, promotion is blocked, and the producer/owner are notified with the exact change.
3. **Given** a source with no contract, **When** the first batches are ingested, **Then** the platform generates an inferred contract marked pending approval; the owner can approve, edit, or reject it.
4. **Given** an approved inferred contract, **When** subsequent data violates it, **Then** the same classification and blocking rules apply as for explicit contracts.

---

### User Story 3 - Quarantine with investigation and replay (Priority: P2)

Failed records and files go to a quarantine area, never silently dropped. Each quarantine entry retains the original record, failure reason, failed test, timestamp, pipeline id, batch id, source, and error details. An engineer investigates quarantine entries through the UI and, after the root cause is fixed, replays the failed records so they re-enter processing without a full re-extraction.

**Why this priority**: Quarantine operationalises "quarantine rather than propagate" and makes failures recoverable; it depends on gates and contracts existing.

**Independent Test**: Can be tested by ingesting a batch with known bad records, verifying each appears in quarantine with complete failure context, fixing the cause, replaying, and verifying the records land correctly with no duplicates.

**Acceptance Scenarios**:

1. **Given** records that failed validation, **When** the batch completes, **Then** every failed record is in quarantine with reason, failed test, batch id, and timestamp.
2. **Given** quarantine entries whose root cause was fixed, **When** an authorised engineer triggers replay, **Then** the records re-enter processing at the appropriate stage and a successful replay removes them from the active quarantine queue.
3. **Given** quarantine entries, **When** an engineer searches them, **Then** results can be filtered by source, pipeline, batch, failure reason, and date range.

---

### User Story 4 - Configurable tests and severity per dataset and environment (Priority: P2)

A data engineer configures tests for a dataset from the standard categories: schema, type, nullability, uniqueness, completeness, validity, referential integrity, reconciliation, freshness, volume, distribution, business rule, security, contract, transformation, and statistical. Each test has a severity: CRITICAL or ERROR (block by default), WARNING (continue, notify), INFORMATIONAL (record only). Severity behaviour is configurable per dataset and per environment (stricter in Production, looser in Development).

**Why this priority**: Configurability makes gates practical across diverse datasets and environments; depends on the gate mechanism.

**Independent Test**: Can be tested by configuring the same dataset differently in Development and Production, feeding identical borderline data, and verifying the different gate outcomes.

**Acceptance Scenarios**:

1. **Given** a test configured as WARNING, **When** it fails, **Then** the pipeline continues, the warning is recorded in the gate report, and a notification is sent.
2. **Given** a test configured as CRITICAL, **When** it fails, **Then** promotion is blocked regardless of all other tests passing.
3. **Given** a freshness test with a 30-minute threshold, **When** data older than the threshold arrives, **Then** the test fails with the actual staleness reported.
4. **Given** a dataset in Development, **When** the same test would block in Production, **Then** the Development behaviour follows its own configured severity, and the environment difference is visible in the configuration.

---

### User Story 5 - Controlled manual override of a failed gate (Priority: P3)

When business circumstances require it (e.g. a known upstream incident), an authorised user overrides a failed gate. The override requires: authorisation check, reason text, expiry time, user identity, timestamp, and impact assessment. The override is recorded permanently, visible in the dataset's history, and expires automatically. The platform never silently bypasses a failed test.

**Why this priority**: Overrides are the safety valve that keeps gates practical; they must exist but are used rarely and depend on everything above.

**Independent Test**: Can be tested by blocking a gate, applying an override with all required fields, verifying promotion proceeds and the override is auditable; then verifying an override missing a required field is rejected, and an expired override no longer permits promotion.

**Acceptance Scenarios**:

1. **Given** a blocked gate and a user with override authority, **When** the user submits an override with reason, expiry, and impact assessment, **Then** promotion proceeds and the override record is permanently attached to the dataset's history.
2. **Given** a user without override authority, **When** the user attempts an override, **Then** the attempt is rejected and recorded.
3. **Given** an expired override, **When** the gate fails again, **Then** promotion is blocked anew; the old override grants no continuing permission.

---

### User Story 6 - Test results as observable metadata (Priority: P3)

Every test execution is recorded as metadata: dataset, pipeline, run id, tests run, passed, warned, failed, overall status, and failed record counts. Engineers and analysts see quality history over time, quality scores per dataset, and can drill from a dashboard summary into an individual failure.

**Why this priority**: Observability makes quality trends visible and supports the "majority of failures detected at ingestion" metric; depends on tests running.

**Independent Test**: Can be tested by running a pipeline several times with varying outcomes and verifying the history, scores, and drill-down all reflect the runs accurately.

**Acceptance Scenarios**:

1. **Given** completed test runs, **When** a user views a dataset's quality history, **Then** the user sees per-run results, trends, and the current quality score.
2. **Given** a failed run, **When** a user drills into it from the dashboard, **Then** the user reaches the specific failing test, its failed records, and the quarantine entries.

---

### Edge Cases

- What happens when the test framework itself errors (infrastructure failure, not data failure)? The gate must fail closed: an unexecuted critical test blocks promotion, and the report distinguishes "test failed" from "test could not run".
- What happens when a gate configuration changes mid-flight (batch already processing)? The batch is evaluated against the gate version active when the batch started; the version is recorded with results.
- What happens when quarantine storage grows unbounded? Quarantine entries follow a retention policy; expiry is recorded, and replay after retention expiry is refused with an explicit message.
- What happens when a replayed record fails again? It returns to quarantine with an incremented attempt count; repeated failures beyond a threshold escalate to the owner.
- What happens when reconciliation passes but volume is anomalous (e.g. 83% below baseline)? Volume/anomaly tests are part of the gate; a CRITICAL volume test blocks even when schema and reconciliation pass.
- What happens when an override is applied and then the underlying data is reprocessed? Reprocessing re-evaluates the gate; the override applies only to the specific blocked run it was granted for, not future runs.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a quality gate at every layer transition (ingestion→Bronze, Bronze→Silver, Silver→Gold, Gold→consumable) composed of configurable tests.
- **FR-002**: Gates MUST fail closed: a critical test that fails — or cannot execute — MUST block promotion.
- **FR-003**: System MUST support the test categories: schema, type, nullability, uniqueness, completeness, validity, referential integrity, reconciliation, freshness, volume, distribution, business rule, security, contract, transformation, and statistical.
- **FR-004**: Every test MUST have a severity level: CRITICAL, ERROR, WARNING, or INFORMATIONAL; CRITICAL and ERROR block by default, WARNING continues with notification, INFORMATIONAL records only.
- **FR-005**: Test configuration and severity behaviour MUST be configurable per dataset and per environment.
- **FR-006**: System MUST validate incoming data against data contracts during ingestion and classify violations as breaking, non-breaking, or warning; breaking violations MUST block promotion.
- **FR-007**: Where no explicit contract exists, system MUST infer a contract from observed schema and metadata, mark it pending approval, and enforce it after approval.
- **FR-008**: System MUST provide a quarantine area retaining for every rejected record/file: original payload, failure reason, failed test, timestamp, pipeline id, batch id, source, and error details.
- **FR-009**: Quarantined records MUST be replayable after root-cause resolution; replay MUST NOT duplicate successfully processed records; repeated replay failures MUST escalate to the dataset owner.
- **FR-010**: Quarantine entries MUST follow a configurable retention policy; replay after retention expiry MUST be refused explicitly.
- **FR-011**: Gate overrides MUST require authorisation, reason, expiry, user identity, timestamp, and impact assessment; incomplete overrides MUST be rejected; silent bypass MUST be impossible.
- **FR-012**: Overrides MUST apply only to the specific blocked run granted, expire automatically, and remain permanently in the dataset's audit history.
- **FR-013**: Every test execution MUST be recorded as metadata: dataset, pipeline, run id, counts of tests/passed/warnings/failed, overall status, failed record identifiers or counts, and the gate configuration version used.
- **FR-014**: System MUST compute and display a quality score per dataset and quality history over time.
- **FR-015**: Users MUST be able to drill from a quality summary into an individual run, failing test, failed records, and related quarantine entries.
- **FR-016**: Gate failures, contract violations, and warning-threshold breaches MUST raise alerts to configured recipients through the platform's notification channels.
- **FR-017**: Freshness and volume tests MUST detect stale data and anomalous volumes (e.g. large deviation from historical baseline) even when schema and reconciliation tests pass.
- **FR-018**: Test definitions, gate configurations, and contracts MUST be version controlled and flow through the GitOps change workflow.
- **FR-019**: Quality behaviour MUST be cloud-independent: identical gate outcomes for identical data and configuration on all supported clouds.
- **FR-020**: Test-first development MUST be supported: contracts and tests can be defined before the transformation exists, and a pipeline can be deployed with its gates already bound.
- **FR-021**: 100% of production datasets MUST have automated quality gates appropriate to their layer before reaching CONSUMABLE state.

### Key Entities

- **Quality Gate**: The test set bound to a layer transition for a dataset. Attributes: gate id, dataset, transition, tests, configuration version, per-environment overrides, decision logic.
- **Test**: A single quality rule. Attributes: category, severity, parameters (thresholds, expressions), applicable environments, owner.
- **Test Result**: One test's outcome in one run: status, measured value, failed record count/identifiers, duration, timestamp.
- **Gate Report**: The aggregate decision for a run: all test results, overall PROMOTE/BLOCK decision, quality score contribution, configuration version.
- **Data Contract**: Schema agreement for a dataset: fields, types, nullability, origin (explicit/inferred), approval status, version history, violation classification rules.
- **Contract Violation**: A detected deviation: change description, classification (breaking/non-breaking/warning), batch affected, action taken.
- **Quarantine Entry**: A rejected record/file with full failure context, replay eligibility, attempt count, and retention expiry.
- **Override**: A granted bypass of a blocked gate: authorising identity, reason, expiry, timestamp, impact assessment, the specific run it applies to.
- **Quality Score**: A dataset's current quality measure derived from recent gate results; feeds the catalog and dashboards.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero knowingly failed quality-gated datasets promoted downstream (constitution metric), verified by quarterly audit of all promotions and overrides.
- **SC-002**: 100% of production datasets have automated quality gates appropriate to their layer.
- **SC-003**: The majority (>70%) of data quality failures are detected at ingestion or before downstream promotion, measured by the stage at which failures are first caught.
- **SC-004**: Every blocked promotion produces an alert within 5 minutes of the gate decision, and every promotion past a failed gate has a complete override record — 100% compliance.
- **SC-005**: Quarantined records are replayable: at least 95% of quarantine entries whose root cause is fixed re-enter processing successfully without duplication.
- **SC-006**: Engineers resolve a gate failure faster over time: median time from BLOCK to resolution decreases quarter over quarter, enabled by drill-down to failing records.
- **SC-007**: Contract violations are classified correctly: 100% of breaking changes in a validation suite block promotion; zero breaking changes pass silently.
- **SC-008**: Identical data and gate configuration produce identical gate outcomes on both supported clouds.

## Assumptions

- The promotion state machine and layer semantics are owned by feature 003 (medallion-processing); this feature supplies the gate decisions that drive transitions.
- Alert delivery channels (email, Slack, Teams, PagerDuty, webhooks) are platform-level notification capabilities; this feature emits alert events and relies on the platform's channel configuration.
- Statistical/AI-driven anomaly detection beyond threshold-based volume/freshness tests is BRD Phase 2/3; MVP anomaly detection is rule/threshold-based (e.g. deviation from historical baseline).
- AI-assisted test generation (agent recommends rules from observed columns) is BRD Phase 3; the MVP supports manual and inferred-contract-based test definition. The recommendation→approval flow in the constitution applies when agents are added.
- Quality framework choice (Great Expectations / Soda / dbt tests / custom) is a planning-time decision per BRD section 45; this spec states required behaviours.
- Quality scores are computed by a documented, deterministic formula over recent test results; the exact formula is a planning-time detail.
