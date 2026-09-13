# Feature Specification: Semantic Layer

**Feature Branch**: `feature/006-semantic-layer`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: "...and build a semantic layer." — this feature covers the business abstraction between physical Gold/Silver data and consumers: metrics, dimensions, measures, relationships, business definitions, and access policies, ensuring one consistent definition of every business term across reporting, AI/ML, and applications.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Define business metrics once, consume everywhere (Priority: P1)

An analytics engineer defines a business metric in the semantic layer — for example "Revenue = sum of order amount where order status is COMPLETED" — bound to Gold (or Silver) datasets, with dimensions (customer, product, time), business definitions in plain language, and an owner. Every consumer (BI reports, analyst queries, AI/ML feature pipelines, applications) that requests "Revenue" receives the same value computed by the same definition. No downstream team re-implements business logic.

**Why this priority**: Semantic consistency is the feature's entire reason to exist ("prevents every downstream team from independently implementing business logic"). Without a single metric definition, the rest has no anchor.

**Independent Test**: Can be tested by defining one metric, consuming it through two different consumption paths, and verifying identical results; then changing the definition through the governed workflow and verifying all consumers reflect the new version.

**Acceptance Scenarios**:

1. **Given** a defined metric with dimensions, **When** two different consumers query the metric for the same dimension values and period, **Then** both receive identical results.
2. **Given** a metric definition change submitted through version control and approved, **When** consumers query afterwards, **Then** results reflect the new definition and the definition version is discoverable.
3. **Given** a metric, **When** a business user views it in the catalog, **Then** they see its plain-language definition, formula, owner, source datasets, and lineage.

---

### User Story 2 - Governed metric lifecycle (Priority: P2)

Semantic definitions (metrics, dimensions, measures, relationships) are version controlled and change through the GitOps workflow: propose → validate → approve → publish. Validation includes semantic tests: metric calculations produce expected results on reference data, dimension relationships hold, aggregations reconcile with the underlying datasets, and filters behave as defined. Breaking definition changes require explicit approval and are communicated to registered consumers.

**Why this priority**: Governance prevents the semantic layer from becoming a new source of inconsistency; depends on definitions existing (P1).

**Independent Test**: Can be tested by submitting a metric change that fails a semantic test (e.g. aggregation no longer reconciles) and verifying publication is blocked; then submitting a correct change and verifying it publishes with version history.

**Acceptance Scenarios**:

1. **Given** a proposed metric change, **When** semantic validation fails, **Then** publication is blocked and the failure detail is reported to the proposer.
2. **Given** an approved breaking change, **When** it is published, **Then** registered consumers of the metric are notified, and the previous version remains documented in history.
3. **Given** any published metric version, **When** a consumer requests results "as of" a prior period, **Then** the definition version used is recorded with the result.

---

### User Story 3 - Access policies on semantic consumption (Priority: P2)

Semantic-layer access respects the platform's security model: consumers only see metrics and dimension members they are authorised for, protected columns remain protected through semantic queries, and row-level restrictions apply. A metric built over a RESTRICTED dataset is only queryable by roles authorised for that classification.

**Why this priority**: The semantic layer must not become a security bypass around the protection policies of feature 005.

**Independent Test**: Can be tested by querying the same metric as two roles with different authorisations and verifying different visibility/results, and by verifying protected column values never appear in semantic query output without authorised detokenisation.

**Acceptance Scenarios**:

1. **Given** a metric over a RESTRICTED dataset, **When** an unauthorised user queries it, **Then** access is denied with a clear reason.
2. **Given** a dimension containing a protected column, **When** any authorised user queries through the semantic layer, **Then** protected values remain masked/tokenised per policy.
3. **Given** row-level restrictions on the source dataset, **When** a user queries a metric, **Then** results include only rows the user is authorised to see.

---

### User Story 4 - Discover and understand business terms (Priority: P3)

A business user searches the catalog for "customer revenue" and finds the certified metric with its definition, owner, quality score, freshness, and consuming teams. Certified definitions are visually distinguished from drafts. Users see which datasets and pipelines feed a metric (lineage) and how recently it refreshed.

**Why this priority**: Discovery drives adoption; depends on definitions and catalog registration existing.

**Independent Test**: Can be tested by searching business terms and verifying the correct certified metrics surface with complete metadata, and that draft definitions are clearly distinguished.

**Acceptance Scenarios**:

1. **Given** a published metric, **When** a user searches its business term, **Then** the metric appears with definition, owner, quality score, freshness, and lineage.
2. **Given** a draft (unpublished) definition, **When** a user searches, **Then** it is either hidden from general users or clearly marked as draft.

---

### Edge Cases

- What happens when a metric's underlying Gold dataset fails its quality gate or is stale? Semantic queries must surface the freshness/quality state with results (or refuse per policy) — never silently serve stale numbers as current.
- What happens when two teams propose conflicting definitions for the same business term? Name uniqueness is enforced per domain; conflicts require resolution (rename, domain scoping, or governance decision) before publication.
- What happens when a source dataset's schema changes break a metric's binding? Semantic validation fails at publish/deploy time, blocking the broken definition; consumers of the last good version are notified of degradation.
- What happens when a metric is deprecated? Consumers are notified, the definition is marked deprecated with a successor reference where applicable, and queries against it return a deprecation notice with results (or are refused after the deprecation period).
- What happens when a dimension relationship produces fan-out (double counting in aggregates)? Semantic tests must detect aggregation anomalies on reference data before publication.
- What happens when query volume against a metric spikes? Semantic queries are subject to platform resource governance; degraded performance is observable, not silent.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a semantic layer defining business metrics, dimensions, measures, relationships, and plain-language business definitions over platform datasets (Gold primarily, Silver where appropriate).
- **FR-002**: A metric defined once MUST return identical results to every authorised consumer path (BI, analyst SQL, AI/ML pipelines, applications); consumers MUST NOT need to re-implement business logic.
- **FR-003**: Semantic definitions MUST be declarative, version controlled, and change through the GitOps workflow (propose → validate → approve → publish).
- **FR-004**: Publication MUST require passing semantic tests: metric calculation correctness on reference data, dimension relationship validity, aggregation reconciliation with underlying datasets, and filter behaviour.
- **FR-005**: Definition changes MUST be classified (breaking / non-breaking); breaking changes MUST require explicit approval and MUST notify registered consumers.
- **FR-006**: Every metric MUST carry: owner, plain-language definition, formula, bound source datasets, lineage, definition version, certification state (draft / published / deprecated), quality score, and freshness.
- **FR-007**: Semantic queries MUST enforce the platform's access policies: role-based visibility of metrics, column-level protection preserved in results, and row-level restrictions applied.
- **FR-008**: Semantic query results MUST report the data freshness and quality state of underlying datasets; serving data known to have failed its quality gate MUST be blocked or explicitly flagged per policy.
- **FR-009**: Business term names MUST be unique within a domain; conflicting definitions MUST be resolvable through domain scoping or governance decision before publication.
- **FR-010**: System MUST support metric deprecation with consumer notification, successor reference, and time-bounded continued availability.
- **FR-011**: Semantic definitions MUST be searchable and discoverable through the catalog, with certified definitions distinguished from drafts.
- **FR-012**: The definition version used MUST be recorded with every query result, enabling reproducibility of past reports.
- **FR-013**: Semantic-layer behaviour MUST be cloud-independent: identical definitions produce identical results on all supported clouds.
- **FR-014**: Semantic tests MUST run automatically on definition change AND on schedule against production data (detecting drift such as aggregation anomalies caused by upstream changes).
- **FR-015**: The semantic layer MUST expose definitions to AI/ML consumers (feature datasets and metric metadata) under the same access policies as human consumers.

### Key Entities

- **Metric**: A named business measure. Attributes: business term, plain-language definition, formula/aggregation, dimensions, bound datasets, owner, version, certification state, quality score, freshness.
- **Dimension**: An axis of analysis (customer, product, time) with members, relationships to other dimensions, and protection status.
- **Measure**: A quantitative column within a dataset that metrics aggregate over.
- **Relationship**: A declared join/association between datasets or dimensions used in metric computation; validated for fan-out anomalies.
- **Semantic Model**: The versioned collection of metrics, dimensions, measures, and relationships for a domain; the unit of publication through GitOps.
- **Semantic Test**: A validation bound to a definition: calculation correctness, reconciliation, relationship validity, filter behaviour; runs at publish time and on schedule.
- **Consumer Registration**: A record of which teams/paths consume which metrics, enabling breaking-change and deprecation notification.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% consistency: the same metric queried through any two consumer paths returns identical results — zero definition-drift incidents per quarter.
- **SC-002**: Zero breaking semantic changes published without approval and consumer notification, verified by audit.
- **SC-003**: Business users find the certified definition of a common business term via catalog search in under 1 minute, in 90% of attempts (usability testing).
- **SC-004**: Downstream re-implementation of business logic drops to zero for metrics published in the semantic layer: consuming teams use published definitions rather than bespoke calculations, measured by review of consuming queries/reports.
- **SC-005**: 100% of semantic queries against protected data enforce access and protection policies — zero protected-value leaks through the semantic layer in security validation.
- **SC-006**: Any published metric result is reproducible: given the recorded definition version and dataset versions, a re-run matches the original result.
- **SC-007**: Semantic tests catch aggregation/relationship defects before publication: zero fan-out double-counting defects reach consumers after passing semantic validation.

## Assumptions

- The semantic layer consumes Gold (and where appropriate Silver) datasets produced under feature 003 and gated by feature 004; it does not define its own storage of business data.
- Access policies, classification, and column protection are owned by feature 005; the semantic layer enforces them, not defines them.
- Catalog registration and search are platform capabilities (feature 003 metadata requirements + feature 007 UI); this feature supplies the semantic metadata to display.
- The semantic-layer technology (Cube, dbt Semantic Layer, or other) is a planning-time decision per BRD section 45; this spec states required behaviours. The constitution requires a "metric/semantic-layer abstraction".
- BI tool integration specifics (looker, Power BI connectors) are out of MVP scope; consumption paths in scope are: analyst SQL/query experience, catalog display, and programmatic access for AI/ML and applications.
- Natural-language querying of metrics is BRD Phase 3 (AI agents); out of scope here.
- The semantic layer is deployable as a platform capability selected at deployment time (feature 001, FR-012).
