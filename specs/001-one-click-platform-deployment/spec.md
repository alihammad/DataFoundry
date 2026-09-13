# Feature Specification: One-Click Platform Deployment

**Feature Branch**: `feature/001-one-click-platform-deployment`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: "Build a platform that can ingest data from various sources in various types into cloud, process it using Medallion architecture and build a semantic layer. All with one click. Build a web UI through which all configurations can be set and the entire platform can be monitored." — this feature covers the one-click deployment of a complete lakehouse environment on AWS or GCP.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deploy a complete lakehouse platform in one click (Priority: P1)

An authorised platform engineer opens the deployment experience, supplies a platform name, selects a cloud provider (AWS or GCP), a region, an environment type (Development, Test, UAT, or Production), and the capabilities to enable (lakehouse storage zones, ingestion, transformation, data quality, catalog, semantic layer, monitoring). The user clicks "Deploy Platform". The system validates the configuration, provisions all required infrastructure (networking, object storage, identity and access management, compute, orchestration, monitoring, secrets management), initialises the Bronze/Silver/Gold storage zones and the metadata catalog, runs health checks, and presents the platform as ready — with no manual cloud-console work.

**Why this priority**: This is the product's headline promise ("new lakehouse environment deployed in less than 30 minutes") and the prerequisite for every other feature. Without it, nothing else can be consumed self-service.

**Independent Test**: Can be fully tested by submitting a valid deployment request for each supported cloud and verifying that, within the target time, all infrastructure components exist, storage zones are initialised, health checks pass, and the platform is reported as ready. Delivers a usable empty governed lakehouse.

**Acceptance Scenarios**:

1. **Given** a user authorised to create platforms, **When** the user submits a complete, valid deployment configuration for GCP and confirms deployment, **Then** the system provisions the platform and reports it ready within 30 minutes, with all selected capabilities operational.
2. **Given** a user authorised to create platforms, **When** the user submits the same logical configuration for AWS, **Then** the resulting platform exposes the identical logical capabilities (storage zones, catalog, ingestion service, monitoring) despite different underlying cloud services.
3. **Given** a deployment in progress, **When** the user views the deployment, **Then** the user sees the current step, completed steps, and any step failures with a human-readable reason.
4. **Given** a deployment request with an invalid configuration (e.g. unsupported region, missing required field, capability dependency not satisfied), **When** the user submits it, **Then** the system rejects the request before provisioning anything and reports each validation error with guidance to fix it.

---

### User Story 2 - Declarative, reproducible environments (Priority: P2)

A platform engineer defines an environment (Development, Test, UAT, or Production) as declarative configuration that is version controlled. The same configuration can be re-applied to recreate the platform identically — supporting disaster recovery ("infrastructure reproducible from code") and promotion of configuration between environments.

**Why this priority**: Reproducibility is a constitutional requirement (Terraform IaC, disaster recovery) and underpins GitOps. It is essential for production trust but the first platform can technically be deployed before it is fully automated.

**Independent Test**: Can be tested by deploying a platform from a saved configuration, destroying the infrastructure, and redeploying from the same configuration, then verifying the recreated platform matches the original in capabilities, settings, and storage layout.

**Acceptance Scenarios**:

1. **Given** a deployed platform, **When** its configuration is exported, **Then** the exported configuration contains every parameter needed to recreate the platform and contains no secrets in plaintext.
2. **Given** a saved platform configuration, **When** an authorised user deploys from it, **Then** the resulting platform matches the configuration exactly, with no manual steps.
3. **Given** a configuration change submitted through the version-control workflow, **When** the change passes validation and approval, **Then** the platform is updated to reflect the change and the change history is retained.

---

### User Story 3 - Capability selection and platform health (Priority: P3)

An authorised user selects which capabilities to enable at deployment time and can later view platform health: infrastructure status, storage utilisation, recent deployments, and recent failures on a single dashboard. Capabilities not selected are not provisioned, avoiding unnecessary cost.

**Why this priority**: Cost-awareness and observability are required "by default", but a platform is still valuable with all capabilities on; selective enablement and health views refine the experience.

**Independent Test**: Can be tested by deploying two platforms with different capability selections and verifying only the selected capabilities exist and are billed/visible, and that the health view reflects the real state of each component.

**Acceptance Scenarios**:

1. **Given** a deployment configuration with the semantic layer disabled, **When** the platform is deployed, **Then** no semantic-layer components are provisioned and the capability can be enabled later through a configuration change.
2. **Given** a running platform, **When** a user opens the platform dashboard, **Then** the user sees cloud, region, environment, component health, storage utilisation, and the most recent deployment and failures.
3. **Given** a platform component has failed its health check, **When** a user views the dashboard, **Then** the failed component is clearly flagged with its failure reason and last check time.

---

### Edge Cases

- What happens when a deployment fails midway (e.g. cloud quota exceeded, permissions insufficient)? The system must report the failed step, leave the partial state inspectable, and offer either retry-from-failed-step or full rollback so no half-provisioned platform is silently abandoned.
- What happens when the target cloud region does not support a selected capability? Validation must reject the combination before provisioning and suggest a supported region.
- What happens when two users deploy platforms with the same name concurrently? Name uniqueness must be enforced per cloud account/project scope, with a clear error to the second user.
- What happens when the deploying user's cloud credentials expire mid-deployment? The deployment must pause safely, record the failure reason, and be resumable after credentials are refreshed — never partially destroy existing resources.
- What happens when a user requests an environment type (Production) that requires stricter controls? Production deployments must enforce additional pre-deployment checks (approval requirement, encryption settings mandatory) and refuse to deploy without them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST allow an authorised user to deploy a complete lakehouse platform through a single user-initiated operation, given: platform name, cloud provider, region, environment type, and capability selection.
- **FR-002**: System MUST support AWS and GCP as deployment targets, exposing the same logical capabilities on both clouds.
- **FR-003**: System MUST validate the full deployment configuration (required fields, region support, capability dependencies, naming rules, authorisation) before provisioning any resource, and MUST report all validation errors at once with remediation guidance.
- **FR-004**: System MUST provision, as part of the deployment: network isolation, object storage with Bronze/Silver/Gold zones, identity and access management with least privilege, compute, orchestration, secrets management, and monitoring.
- **FR-005**: System MUST initialise the metadata catalog and storage zone structure during deployment, before the platform is reported ready.
- **FR-006**: All infrastructure MUST be provisioned from versioned infrastructure-as-code definitions; no resource may be created through manual console operations as part of the standard flow.
- **FR-007**: System MUST run platform health checks after provisioning and MUST report the platform as ready only when all health checks for the selected capabilities pass.
- **FR-008**: System MUST show deployment progress as an ordered list of steps with per-step status (pending, running, succeeded, failed) and failure reasons.
- **FR-009**: On deployment failure, system MUST offer retry-from-failed-step and rollback options; rollback MUST remove resources created by the failed deployment and MUST NOT touch pre-existing resources.
- **FR-010**: System MUST support Development, Test, UAT, and Production environment types, with environment-specific configuration and stricter pre-deployment controls for Production (explicit approval, mandatory encryption settings).
- **FR-011**: Platform configuration MUST be declarative, exportable, version controlled, and re-appliable to recreate an identical platform; exported configuration MUST NOT contain plaintext secrets.
- **FR-012**: System MUST allow capabilities (ingestion, transformation, data quality, catalog, semantic layer, monitoring) to be enabled or omitted at deployment time, and MUST allow enabling an omitted capability later through a configuration change.
- **FR-013**: System MUST enforce platform-name uniqueness within a cloud account/project scope and reject duplicates with a clear error.
- **FR-014**: System MUST record every deployment (who, when, configuration, outcome, duration) as auditable history.
- **FR-015**: System MUST support adding a new cloud provider without modifying the logical platform configuration format or existing providers' behaviour.
- **FR-016**: System MUST complete deployment of a standard platform (all MVP capabilities, single region) in under 30 minutes under normal cloud conditions.
- **FR-017**: All data stores created by the deployment (object storage, metadata, logs, backups) MUST have encryption at rest enabled from creation; encryption in transit MUST be enforced for all platform endpoints.
- **FR-018**: System MUST verify the deploying user holds the required cloud permissions before provisioning and MUST fail fast with a precise list of missing permissions when they are absent.

### Key Entities

- **Platform**: A deployed lakehouse environment. Attributes: name, cloud provider, region, environment type, enabled capabilities, status (deploying, ready, degraded, failed), creation timestamp, owner, configuration reference.
- **Deployment Configuration**: The declarative definition of a platform: cloud, region, environment, capabilities, storage settings, encryption settings, networking settings. Version controlled; contains no plaintext secrets.
- **Deployment Run**: A single execution of a deployment or update. Attributes: run id, platform, configuration version, step list with statuses and timestamps, outcome, failure reasons, initiated-by identity.
- **Capability**: A logical platform function (object storage, compute, orchestration, metadata, catalog, ingestion, quality, semantic layer, monitoring) that maps to cloud-specific implementations per provider.
- **Environment Type**: Development, Test, UAT, or Production; drives configuration defaults and control strictness.
- **Health Check Result**: Per-component status with last check time and failure detail; feeds the platform dashboard.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A new lakehouse platform with all MVP capabilities is deployed and reported ready in under 30 minutes on either supported cloud, in 95% of deployments under normal cloud conditions.
- **SC-002**: 100% of deployments are fully reproducible from versioned configuration — a destroyed platform can be recreated from its configuration with zero manual cloud-console steps.
- **SC-003**: A platform deployed on AWS and the same logical configuration deployed on GCP expose an identical set of logical capabilities, verified by a capability-parity checklist, with zero platform-behaviour differences visible to data teams.
- **SC-004**: 100% of invalid deployment configurations are rejected before any resource is provisioned, with all validation errors reported in a single response.
- **SC-005**: After a mid-deployment failure, a user can restore to a clean state (retry succeeds or rollback completes) within 15 minutes, with no orphaned resources remaining after rollback.
- **SC-006**: Zero plaintext secrets present in any exported configuration, deployment record, or log.
- **SC-007**: 90% of first-time authorised users complete a platform deployment successfully without external help, using only the deployment experience and its validation messages.

## Assumptions

- The deploying user already holds (or can request through their cloud administrator) a cloud account/project with sufficient quotas and permissions; the platform does not create cloud accounts.
- "One click" means one user-initiated deployment operation after configuration entry; configuration entry itself is a guided form, not a single literal button.
- MVP capability set follows BRD Phase 1: networking, object storage, IAM, Bronze/Silver/Gold zones, ingestion service, orchestration, catalog/metadata, monitoring. Semantic layer is deployable as a capability but specified separately (feature 006).
- Terraform is the infrastructure-as-code mechanism per the constitution; the spec states the reproducibility outcome, not the tool, but planning may rely on the constitutional mandate.
- Identity for platform users is federated with the organisation's existing identity provider via cloud-native IAM; a separate user directory is out of scope.
- Cost optimisation beyond capability-selective provisioning (budgets, alerts) is out of scope for this feature.
- Concurrent deployment of multiple distinct platforms is supported; parallel deployment of the same platform is not (a platform has at most one active deployment run).
