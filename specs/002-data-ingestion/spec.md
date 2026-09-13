# Feature Specification: Self-Service Data Ingestion

**Feature Branch**: `feature/002-data-ingestion`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: "Build a platform that can ingest data from various sources in various types into cloud..." — this feature covers the standardised ingestion framework that lands data from enterprise sources into the Bronze layer, configured self-service through a wizard.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Configure and run ingestion from a relational database (Priority: P1)

A data engineer opens the "Add Data Source" wizard, selects a database type (PostgreSQL or SQL Server for MVP), enters connection details, and tests the connection. The platform discovers the schema and lists available tables. The engineer selects tables, chooses an ingestion mode (full or incremental) and a schedule, and selects Bronze as the target. The engineer validates and saves the configuration; the platform creates the ingestion pipeline automatically — no custom code. On schedule, data lands in Bronze with ingestion metadata (source system, table, timestamp, batch id, record count, status).

**Why this priority**: Database ingestion is the most common enterprise onboarding path and the core of the "source onboarded in under 30 minutes" promise. Without it the lakehouse has no data.

**Independent Test**: Can be tested by pointing the wizard at a sample PostgreSQL database, configuring two tables for incremental ingestion, running the pipeline, and verifying the records, metadata, and schedule behaviour in Bronze. Delivers queryable raw data in the lakehouse.

**Acceptance Scenarios**:

1. **Given** valid connection details for a reachable database, **When** the user tests the connection in the wizard, **Then** the platform confirms connectivity and displays the discovered schema within one minute.
2. **Given** a saved ingestion configuration for selected tables, **When** the scheduled time arrives, **Then** the platform ingests the data into Bronze and records batch metadata including record counts and ingestion status.
3. **Given** an incremental ingestion configuration, **When** the pipeline runs a second time, **Then** only new or changed records since the last successful run are ingested, with no duplicates in Bronze for the same source records.
4. **Given** invalid credentials or an unreachable host, **When** the user tests the connection, **Then** the platform reports a specific, actionable error (authentication failed vs. network unreachable vs. database not found) and does not save the configuration as deployable.

---

### User Story 2 - Ingest files from object storage and file drops (Priority: P2)

A data engineer configures ingestion of files (CSV, JSON, Parquet) arriving in a cloud object-storage location or delivered via secure file transfer. The platform detects new files, validates them (format, encoding, readability, checksum where provided), ingests them into Bronze preserving the source layout, and routes invalid files to quarantine with a failure reason instead of propagating them.

**Why this priority**: File-based sources are the second most common MVP path and exercise the ingestion-validation and quarantine behaviour that the quality feature depends on.

**Independent Test**: Can be tested by dropping valid and deliberately corrupted files into a watched location, running ingestion, and verifying valid files land in Bronze with metadata while corrupted files land in quarantine with reasons.

**Acceptance Scenarios**:

1. **Given** a configured file source location, **When** new files matching the configured pattern arrive, **Then** the platform ingests them into Bronze on the next run and records file-level metadata (name, size, checksum, ingestion timestamp).
2. **Given** a file that fails validation (corrupted, wrong format, unreadable), **When** ingestion runs, **Then** the file is routed to quarantine with the failure reason, the remaining valid files are still ingested, and the batch status reflects partial success.
3. **Given** the same file is delivered twice (identical checksum), **When** ingestion runs, **Then** the duplicate is detected and recorded, and the data is not double-loaded into Bronze.

---

### User Story 3 - Ingestion validation before promotion (Priority: P2)

Before ingested data becomes available to downstream processing, the platform runs ingestion-level checks: schema compatibility against the expected or inferred contract, record-count reconciliation against the source, and file security checks (encrypted where required, from an approved source). Data that fails a critical check is marked INGESTED but not INGESTION_VALIDATED, blocking promotion to downstream layers.

**Why this priority**: Shift-left validation is a constitutional principle ("detect as early as possible") and the gate that keeps the Medallion layers clean. Equal priority with file ingestion because both feed the quality gates.

**Independent Test**: Can be tested by ingesting a batch whose source schema changed incompatibly (e.g. an identifier column changed type) and verifying the batch is blocked from promotion, an alert is raised, and the failure detail names the offending column and change.

**Acceptance Scenarios**:

1. **Given** a source whose schema matches the recorded contract, **When** ingestion completes, **Then** the batch transitions to INGESTION_VALIDATED and is eligible for Bronze processing.
2. **Given** a source that introduced a breaking schema change, **When** ingestion completes, **Then** the batch is blocked from promotion, the change is classified (breaking / non-breaking / warning), and the responsible data engineer is alerted with the change detail.
3. **Given** a source with no recorded contract, **When** the first ingestion completes, **Then** the platform infers a contract from the observed schema and marks it as pending owner approval.
4. **Given** source record count 1,000,000 and ingested count 999,870, **When** reconciliation runs, **Then** the batch fails reconciliation with the difference reported, and promotion is blocked until resolved or explicitly overridden per policy.

---

### User Story 4 - Manage and monitor ingestion pipelines (Priority: P3)

A data engineer views all configured sources and pipelines, triggers a run manually, pauses or resumes a schedule, retries a failed run, and inspects execution history, logs, and per-run metrics (records processed, duration, outcome).

**Why this priority**: Operational control is required for day-2 use, but initial value is delivered once ingestion runs on schedule with alerting.

**Independent Test**: Can be tested by manually triggering, pausing, and retrying a configured pipeline and verifying the history and logs reflect each action accurately.

**Acceptance Scenarios**:

1. **Given** a saved pipeline, **When** the user triggers a manual run, **Then** the run executes immediately and appears in execution history with live status.
2. **Given** a failed run, **When** the user retries it, **Then** the retry re-processes only what is needed to complete the batch without duplicating already-ingested records.
3. **Given** a paused pipeline, **When** its schedule elapses, **Then** no run is started and the pause state is visible in the pipeline list.

---

### Edge Cases

- What happens when the source system is unreachable mid-run? The run fails safely with a partial-batch record; already-transferred data is either completed atomically or discarded so Bronze never contains a torn batch; the schedule retries per policy.
- What happens when a source table is dropped or renamed after configuration? The next run detects the missing object, blocks the batch, alerts the owner, and other tables in the same pipeline continue unaffected.
- What happens when the source sends a column with a changed type (integer to string)? Classified as a breaking contract change; batch blocked from promotion; quarantine holds affected records if partial.
- What happens when credentials stored for a source expire or are rotated? Runs fail with an explicit "authentication failed" reason pointing at the stored secret; the platform never logs credential values.
- What happens when a file arrives while a previous run for the same source is still in progress? Runs for the same source are serialised or the new file is picked up by the next run — never two concurrent writes to the same Bronze location.
- What happens when ingestion volume spikes far above the historical baseline? The run completes but the volume anomaly is flagged for review before promotion (anomaly detection detail belongs to the quality-gates feature).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support ingestion from PostgreSQL, SQL Server, CSV files, JSON files, Parquet files, and cloud object-storage locations (AWS and GCP) in the MVP scope.
- **FR-002**: System MUST provide a guided configuration experience (wizard) through which a user can define a source, test connectivity, select tables/files, choose ingestion mode, set a schedule, and select the target zone — without writing code.
- **FR-003**: System MUST support full and incremental ingestion modes for database sources; incremental runs MUST NOT duplicate previously ingested records.
- **FR-004**: System MUST discover and display the source schema (tables, columns, types) during configuration, within one minute for typical schemas.
- **FR-005**: System MUST store source credentials in the platform's secrets management; credentials MUST NEVER appear in configuration exports, logs, or the user interface.
- **FR-006**: System MUST validate files before ingestion: existence, readability, format, encoding, and checksum where provided; files failing validation MUST be routed to quarantine with a failure reason and MUST NOT propagate.
- **FR-007**: System MUST detect duplicate file deliveries (identical checksum) and MUST NOT double-load them.
- **FR-008**: Every ingested batch MUST carry metadata: source system, source object (table/file), ingestion timestamp, batch id, pipeline id, record count, and ingestion status.
- **FR-009**: System MUST run ingestion-level validation before promotion: schema/contract compatibility and source-to-Bronze record-count reconciliation. Batches failing a critical check MUST be blocked from promotion and MUST raise an alert.
- **FR-010**: Where no explicit source contract exists, system MUST infer a contract from observed schema and metadata and mark it pending approval; contract violations MUST be classified as breaking, non-breaking, or warning.
- **FR-011**: System MUST support scheduled (recurring) and manually triggered runs; schedules MUST be configurable per source (e.g. every 15 minutes, hourly, daily).
- **FR-012**: System MUST serialise or safely coordinate runs against the same source/destination so concurrent runs never produce torn or duplicated Bronze data.
- **FR-013**: System MUST record execution history per pipeline: run id, trigger type, start/end time, records processed, outcome, and failure reason; users MUST be able to view logs and metrics per run.
- **FR-014**: Users MUST be able to pause, resume, and retry pipelines; a retry MUST complete the batch without duplicating already-ingested records.
- **FR-015**: On mid-run source failure, system MUST fail safely: no partial batch is presented as complete, and the failure is recorded with enough detail to resume or replay.
- **FR-016**: All data transfer from sources MUST use encrypted channels; where the source provides files pre-encrypted, the platform MUST accept and preserve them per the security feature's decryption policy.
- **FR-017**: Ingestion configuration MUST be declarative, version controlled, and portable across clouds — the same logical source definition MUST work when the platform is redeployed on the other supported cloud.
- **FR-018**: System MUST ingest into the Bronze zone using the platform's standard layout (source-aligned, partitioned by ingestion date) so data is replayable and auditable.
- **FR-019**: A common data source MUST be configurable and first data landed in under 30 minutes for a user with source access.
- **FR-020**: System MUST raise an alert to the pipeline owner when a run fails, when a breaking schema change is detected, or when reconciliation fails.

### Key Entities

- **Data Source**: A configured origin of data. Attributes: type (database, file, object storage), connection reference (host/database or location), credential reference (secret, never plaintext), owner.
- **Ingestion Configuration**: Per-source definition: selected tables/files, ingestion mode (full/incremental), incremental cursor column where applicable, schedule, target zone, validation settings. Declarative and version controlled.
- **Source Contract**: The expected schema agreement for a source object: columns, types, nullability; origin (explicit or inferred); approval status; change classification rules.
- **Ingestion Pipeline**: The executable unit created from an ingestion configuration. Attributes: pipeline id, state (active/paused), schedule, owner.
- **Batch**: One unit of ingested data. Attributes: batch id, pipeline id, source object, record count, checksum where applicable, status (INGESTED, INGESTION_VALIDATED, FAILED, QUARANTINED), timestamps.
- **Run**: One pipeline execution. Attributes: run id, trigger (scheduled/manual/retry), start/end, records processed, outcome, failure reason, log reference.
- **Quarantine Record**: A rejected file, record, or batch with: original payload reference, failure reason, failed check, timestamp, pipeline id, batch id, source.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A common data source (supported database or file drop) is onboarded — configured, validated, and first data landed in Bronze — in under 30 minutes, in 90% of onboardings.
- **SC-002**: 70–90% reduction in custom ingestion code for supported sources: zero lines of source-specific code written by data engineers for the MVP source types.
- **SC-003**: 100% of ingested batches carry complete ingestion metadata and are traceable from Bronze back to source object and run.
- **SC-004**: Zero batches with a failed critical ingestion check are promoted downstream without an explicit recorded override.
- **SC-005**: Incremental ingestion produces zero duplicate records across repeated runs, verified by reconciliation on a test dataset of at least one million records.
- **SC-006**: Over 99% of scheduled runs for stable sources complete successfully.
- **SC-007**: 100% of source credential usages go through secrets management; zero credentials found in any log, export, or UI capture during security review.
- **SC-008**: The same logical ingestion configuration deploys and runs on both supported clouds without modification.

## Assumptions

- MVP source types are limited to BRD Phase 1: PostgreSQL, SQL Server, CSV, and S3/GCS files. SaaS connectors, streaming (Kafka/Pub/Sub/Kinesis), Oracle, MySQL, XML, and Excel are out of scope for this feature and deferred to later phases.
- Reusable ingestion frameworks (e.g. Airbyte) are an implementation option to be evaluated during planning per the BRD; this spec states outcomes, not the framework.
- Change-data-capture (CDC) ingestion is deferred to Phase 2 per BRD; incremental (cursor-based) ingestion is in MVP scope.
- The quarantine zone, quality-gate severity model, and override workflow are specified in the data-quality-gates feature; this feature relies on them and defines the ingestion-side hand-off.
- Source-side file encryption handling (keys, decryption policy) is specified in the security feature; this feature only requires that encrypted files are accepted and preserved.
- Source systems are reachable from the platform's network (via private connectivity or approved endpoints); setting up source-side network access is an operational prerequisite, not part of this feature.
- Timezone for schedules is the platform's configured timezone, consistent across environments.
