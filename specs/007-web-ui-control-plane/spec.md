# Feature Specification: Web UI Control Plane

**Feature Branch**: `feature/007-web-ui-control-plane`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: "Build a web UI through which all configurations can be set and the entire platform can be monitored." — this feature covers the modern web-based UI that acts as the primary control plane: platform creation, data source configuration, pipeline management, dataset browsing, catalog, quality monitoring, dashboards, and administration — for users who do not interact with infrastructure code or cloud consoles directly.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Platform dashboard: single-pane health view (Priority: P1)

An authorised user opens the dashboard and sees the platform at a glance: cloud, region, environment, infrastructure health, pipeline counts (healthy/failed/running), overall data quality score, storage utilisation, compute utilisation, cost summary, recent failures, and recent deployments. From any summary tile the user drills into the underlying detail (a failed pipeline's run history, a dataset's quality report).

**Why this priority**: The dashboard is the entry point for "the entire platform can be monitored" — the user's explicit request. Everything else in the UI hangs off navigation established here.

**Independent Test**: Can be tested by deploying a platform with known state (some healthy pipelines, one failure) and verifying every dashboard figure matches the real state and drill-downs navigate correctly.

**Acceptance Scenarios**:

1. **Given** a running platform, **When** a user opens the dashboard, **Then** all summary figures (pipelines, quality, storage, cost, failures, deployments) reflect actual current state within a defined refresh interval.
2. **Given** a failed pipeline, **When** the user clicks the failures tile, **Then** the user reaches the failure list and can drill into the specific run, its logs, and its gate report.
3. **Given** multiple deployed platforms, **When** a user switches platform context, **Then** the whole UI (dashboard, lists, details) reflects the selected platform.

---

### User Story 2 - Configure everything through the UI (Priority: P1)

A user performs all day-to-day configuration through guided UI experiences, without touching infrastructure code or cloud consoles: create a platform (feature 001's deployment wizard), add and configure data sources (feature 002's wizard), define and bind quality tests and gates (feature 004), set classifications and protection policies (feature 005), and manage semantic definitions' approval workflows (feature 006). Every configuration change made in the UI is persisted through the same version-controlled, approval-based workflow as code-made changes — the UI never bypasses GitOps.

**Why this priority**: "All configurations can be set" is the user's explicit requirement and the self-service promise. Equal priority with the dashboard: monitor and configure are the two halves of a control plane.

**Independent Test**: Can be tested by completing an end-to-end journey purely in the UI — create platform, add source, configure tests, classify data — and verifying each change appears in version control with the correct approval state and takes effect.

**Acceptance Scenarios**:

1. **Given** an authorised user, **When** they complete the data source wizard in the UI, **Then** the ingestion configuration is created, validated, version controlled, and deployable without any manual file editing.
2. **Given** a configuration change requiring approval (e.g. Production change), **When** the user submits it in the UI, **Then** it enters the approval workflow, shows its pending state, and only takes effect after approval.
3. **Given** a user without permission for a configuration area, **When** they navigate there, **Then** edit actions are hidden or disabled with a clear explanation; read access follows their role.
4. **Given** any UI-made configuration change, **When** inspected in version control, **Then** it is indistinguishable in governance terms from a code-made change (same validation, same audit trail).

---

### User Story 3 - Pipeline and run management (Priority: P2)

A data engineer manages pipelines through the UI: view all pipelines with state, trigger runs, pause/resume schedules, retry failures, and inspect execution history, logs, metrics, and failure details per run. Quarantine queues are browsable with filters (source, pipeline, batch, reason, date) and replay can be triggered for fixed entries.

**Why this priority**: Day-2 operations for ingestion/processing; depends on the pipelines and quarantine existing (features 002–004).

**Independent Test**: Can be tested by exercising each pipeline action in the UI against a live pipeline and verifying the resulting state, history, and logs match.

**Acceptance Scenarios**:

1. **Given** an active pipeline, **When** the user triggers a manual run from the UI, **Then** the run starts, shows live status, and lands in execution history.
2. **Given** a failed run, **When** the user retries from the UI, **Then** the retry runs without duplicating ingested data and the history links retry to original.
3. **Given** quarantine entries, **When** the user filters by failure reason and triggers replay on fixed entries, **Then** replay executes and entry states update.

---

### User Story 4 - Catalog browsing and dataset exploration (Priority: P2)

An analyst searches the catalog ("customer revenue"), sees results with layer, owner, quality score, freshness, and consumers, and opens a dataset to view: schema, sample (subject to protection policies), quality history, lineage graph (upstream and downstream, navigable), protection status per column, and business metadata. From the dataset the analyst launches a query in the SQL editor, saves and shares queries, and downloads results per policy.

**Why this priority**: The analyst experience (BRD section 17) makes the platform's data usable; depends on catalog metadata from features 003/006.

**Independent Test**: Can be tested by searching a seeded catalog, opening a dataset, verifying all metadata tabs render real data, running and saving a query, and downloading results with protection policies applied.

**Acceptance Scenarios**:

1. **Given** catalog metadata, **When** a user searches a business term, **Then** matching datasets and metrics return ranked with owner, quality, and freshness visible.
2. **Given** a dataset with lineage, **When** the user opens the lineage view, **Then** upstream sources and downstream consumers render as a navigable graph.
3. **Given** a dataset with protected columns, **When** the user previews or queries it, **Then** protected values appear masked/tokenised per the user's rights.
4. **Given** a saved query, **When** the user shares it with a colleague, **Then** the colleague can open and run it subject to their own access rights.

---

### User Story 5 - Quality and monitoring views (Priority: P3)

A user monitors data quality across the platform: per-dataset quality scores and trends, gate run history with drill-down to failing tests and records, contract violation feed, freshness and volume anomalies, and alert history. An operations user sees observability dashboards: pipeline success rates, durations, throughput, infrastructure utilisation, and cost by pipeline/dataset.

**Why this priority**: Deep operational insight builds on the P1 dashboard and quality metadata; high value for operators but the platform functions before these views are complete.

**Independent Test**: Can be tested by generating known quality events (failed gate, contract violation, stale data) and verifying each appears in the correct view with accurate drill-down.

**Acceptance Scenarios**:

1. **Given** a gate failure, **When** a user opens the quality view for that dataset, **Then** the failing run, test, and failed-record drill-down are reachable within two navigation steps.
2. **Given** alert history, **When** a user filters by time range and severity, **Then** matching alerts display with their delivery status.
3. **Given** cost data, **When** a user views cost by pipeline, **Then** figures reconcile with the platform's cost observability source.

---

### User Story 6 - Administration and access management (Priority: P3)

A platform administrator manages the platform through the UI: users and roles (RBAC at platform, dataset, and column scope), approval workflows (who can approve Production changes, overrides, semantic publications), notification channel configuration, environment settings, and audit log search. All administration actions are themselves audited.

**Why this priority**: Administration is required for multi-team operation but a single-team pilot can run with pre-configured roles.

**Independent Test**: Can be tested by creating a role with scoped permissions, assigning a user, and verifying the user's UI capabilities match exactly; then searching the audit log for the administration actions performed.

**Acceptance Scenarios**:

1. **Given** an administrator, **When** they create a role scoped to specific datasets with column restrictions, **Then** users with that role see exactly the scoped capabilities across the UI.
2. **Given** an override approval workflow, **When** a user requests a gate override, **Then** configured approvers receive the request in the UI and can approve/deny with recorded reasoning.
3. **Given** any administration action, **When** the audit log is searched, **Then** the action appears with actor, timestamp, and before/after state.

---

### Edge Cases

- What happens when the UI is used concurrently by two users editing the same configuration? Optimistic concurrency: the second save is rejected with a conflict showing the current version; no silent overwrite.
- What happens when a dashboard's backing service is down? The affected tile shows a stale/unavailable state with last-known timestamp — never a misleading zero or blank.
- What happens when a user's session expires mid-wizard? Draft state is preserved; after re-authentication the user resumes where they left off.
- What happens when a drill-down target was deleted (pipeline removed since the dashboard rendered)? Navigation reports "resource no longer exists" and returns the user to a valid view.
- What happens on a small screen or low bandwidth? The UI remains functional (responsive layout, paginated lists); monitoring and configuration are not desktop-only.
- What happens when a user attempts a UI action whose backend workflow fails validation? The UI surfaces the specific validation errors inline; partial configuration is never silently applied.
- What happens when protected data would appear in a UI sample/preview? Previews enforce the same protection policies as queries; there is no privileged UI path to raw protected values.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a modern web-based UI that is the primary control plane for users who do not interact with infrastructure code or cloud consoles.
- **FR-002**: UI MUST provide a platform dashboard showing: platform identity (cloud, region, environment), infrastructure health, pipeline health counts, data quality score, storage and compute utilisation, cost summary, recent failures, and recent deployments.
- **FR-003**: Every dashboard summary MUST support drill-down to its underlying detail within at most two navigation steps.
- **FR-004**: All platform configuration MUST be settable through the UI: platform deployment, data sources, ingestion settings, pipelines/schedules, quality tests and gates, classifications and protection policies, semantic definition workflows, notifications, and environment settings.
- **FR-005**: UI-made configuration changes MUST flow through the same version control, validation, and approval workflow as code-made changes; the UI MUST NOT bypass GitOps.
- **FR-006**: UI MUST support pipeline operations: view, trigger, pause, resume, retry, and inspect execution history, logs, metrics, and failure details.
- **FR-007**: UI MUST provide quarantine browsing with filters (source, pipeline, batch, failure reason, date range) and replay initiation for authorised users.
- **FR-008**: UI MUST provide catalog search over datasets and metrics with results showing layer, owner, quality score, freshness, and consumers.
- **FR-009**: UI MUST provide a dataset detail view: schema, policy-compliant sample preview, quality history, protection status per column, business metadata, and a navigable lineage graph (upstream and downstream).
- **FR-010**: UI MUST provide a SQL query experience over Silver/Gold datasets with save, share, and download; all subject to the querying user's access and protection policies.
- **FR-011**: UI MUST provide quality monitoring views: per-dataset scores and trends, gate run history with test-level and record-level drill-down, contract violation feed, anomaly indicators, and alert history with filters.
- **FR-012**: UI MUST provide observability views: pipeline success rate, duration, throughput, infrastructure utilisation, and cost by pipeline/dataset.
- **FR-013**: UI MUST enforce role-based access on every view and action: users see and can do only what their roles permit; denied areas are hidden or disabled with explanation.
- **FR-014**: UI MUST provide administration: user/role management at platform, dataset, and column scope; approval workflow configuration; notification channel configuration; and audit log search by time, identity, resource, and action.
- **FR-015**: All administration and configuration actions performed through the UI MUST be audited with actor, timestamp, and before/after state.
- **FR-016**: UI MUST support approval workflows in-place: pending requests (Production changes, gate overrides, semantic publications, contract approvals) are visible to approvers with approve/deny and recorded reasoning.
- **FR-017**: UI MUST handle concurrent editing safely: conflicting saves are rejected with the current version shown; no silent overwrites.
- **FR-018**: UI MUST degrade honestly: when a backing service or data feed is unavailable, affected views show a stale/unavailable state with last-known timestamp, never misleading values.
- **FR-019**: UI MUST be responsive (usable on small screens) and MUST paginate or virtualise large lists; monitoring and configuration MUST NOT be desktop-only.
- **FR-020**: UI MUST support multi-platform contexts: users with rights to several platforms switch context, and all views respect the selected platform.
- **FR-021**: UI MUST preserve in-progress wizard state across session expiry, resuming after re-authentication.
- **FR-022**: UI MUST never display secrets, key material, credential values, or unprotected sensitive values in any view, preview, log display, or download.
- **FR-023**: UI behaviour MUST be cloud-independent: identical screens, workflows, and capabilities regardless of the platform's underlying cloud.

### Key Entities

- **UI Role**: A named permission set scoping views and actions (platform scope, dataset scope, column scope); assigned to users; enforced on every request.
- **Dashboard View**: A composed summary of platform state figures with drill-down links; per-platform context.
- **Pending Approval**: A workflow item awaiting decision: type (production change, override, semantic publication, contract), requester, payload, approvers, decision state, reasoning.
- **Saved Query**: A user's stored SQL with metadata (owner, dataset bindings, sharing settings); execution always re-evaluates the runner's access rights.
- **Audit Trail Entry** (UI-originated): Actor, timestamp, action, resource, before/after state; searchable from the administration area.
- **Notification Channel Configuration**: Per-platform alert routing settings (channels and recipients by event type) managed through the UI.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A data engineer completes the full self-service journey (platform exists → source configured → pipeline running → dataset browsable) using only the UI, with zero cloud-console or code-editor interactions, in under 45 minutes.
- **SC-002**: 90% of first-time users complete the data source wizard successfully without external help (usability testing).
- **SC-003**: Any platform state figure shown on the dashboard matches the backing system state within a 60-second refresh window; zero misleading figures during partial outages (stale-state handling verified).
- **SC-004**: 100% of UI-made configuration changes appear in version control with approval state — zero GitOps bypasses found in audit.
- **SC-005**: Drill-down from any dashboard failure indicator to the failing test and failed records takes at most two navigation steps, verified by walkthrough.
- **SC-006**: Zero protected values, secrets, or credentials exposed in any UI view, preview, export, or network response, verified by security review.
- **SC-007**: The UI is fully functional for all MVP workflows on both supported clouds with identical screens and capabilities (cloud-parity walkthrough).
- **SC-008**: Analysts adopt the UI query experience: a majority of Silver/Gold ad-hoc queries run through the platform UI rather than external tools, measured after two quarters of availability.

## Assumptions

- The UI consumes platform capabilities defined in features 001–006; it adds no new business behaviour — it exposes and governs existing capabilities. Where this spec mentions a workflow (wizards, approvals, drill-downs), the underlying capability is owned by the respective feature.
- UI sections beyond MVP scope per BRD Phase 1 (APIs management, Agents management, full semantic-layer authoring UI) are deferred; MVP UI covers: platform creation, data source configuration, pipeline monitoring, dataset browsing, quality monitoring, dashboard, and administration basics.
- Authentication uses the organisation's identity provider (federated, per feature 001 assumption); the UI does not manage passwords.
- Notebooks (BRD section 17 mentions "create notebooks") are out of MVP UI scope; the SQL editor with save/share covers MVP analyst querying.
- Cost figures come from the platform's cost observability feed (cloud billing integration); the UI displays, not computes, cost.
- Internationalisation, theming/white-labelling, and offline support are out of scope.
- Frontend technology choice is a planning-time decision; this spec states behaviour and experience requirements only.
