# Feature Specification: Security and Data Protection

**Feature Branch**: `feature/005-security-data-protection`

**Created**: 2026-09-13

**Status**: Draft

**Input**: User description: platform must ingest, process, and serve data with enterprise-grade security — this feature covers encryption in depth (source-side, in transit, at rest, column level), classification-driven protection policies, tokenisation and masking, key management, secure access enforcement, and security auditability.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Classification-driven data protection (Priority: P1)

A data owner classifies a dataset (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED, or HIGHLY RESTRICTED) and the platform maps the classification to an enforceable protection policy. Sensitive columns (personal information, financial data, credentials) are identified and protected per policy — encryption, tokenisation, masking, hashing, redaction, or pseudonymisation — without the data engineer choosing mechanisms by hand. Organisations can define their own classification-to-protection mappings.

**Why this priority**: Classification is the root of the whole protection model; every other security behaviour keys off it. The constitution mandates classification-driven protection.

**Independent Test**: Can be tested by classifying a dataset RESTRICTED with a sensitive column, ingesting data, and verifying the column is protected per the mapped policy in all layers, while non-sensitive columns remain queryable.

**Acceptance Scenarios**:

1. **Given** a dataset classified RESTRICTED with an email column marked sensitive, **When** data is ingested and processed, **Then** the email column is protected by the policy-mapped mechanism in Bronze, Silver, and Gold, and the catalog shows its protection status.
2. **Given** an organisation-defined classification-to-protection mapping, **When** a dataset's classification changes, **Then** the new protection policy applies to subsequent processing and the change is audited.
3. **Given** a user without access rights to a RESTRICTED column, **When** the user queries the dataset, **Then** protected values are masked or withheld per policy; the query otherwise succeeds on unprotected columns.

---

### User Story 2 - Encryption in depth (Priority: P1)

All data is encrypted at rest (every layer, metadata, logs, temporary and backup storage) and in transit (all transfers use encrypted channels). Files containing sensitive data can be encrypted at the source before transmission; the platform accepts pre-encrypted files, verifies their integrity and authenticity, and processes them per policy. Both platform-managed and customer-managed keys are supported.

**Why this priority**: "Encryption by default" is a constitutional non-negotiable and a baseline for any production data platform.

**Independent Test**: Can be tested by verifying: storage-level encryption is enabled on all zones; a plaintext transfer attempt is rejected; a source-encrypted file is accepted, verified, and processed; and a customer-managed key configuration works end to end.

**Acceptance Scenarios**:

1. **Given** a deployed platform, **When** any data is written to any layer or metadata store, **Then** it is encrypted at rest with the configured key management mode.
2. **Given** a source delivering a pre-encrypted file with encryption metadata, **When** ingestion runs, **Then** the platform verifies integrity, signature, and encryption status before processing, and rejects files failing verification.
3. **Given** a customer-managed key configuration, **When** data is written and read, **Then** the customer's key is used and key usage is audited.
4. **Given** any data transfer between platform components or from sources, **When** the transfer occurs, **Then** it uses an encrypted channel; unencrypted channel attempts fail.

---

### User Story 3 - Tokenisation of highly sensitive values (Priority: P2)

For highly sensitive attributes (PII consumed by analytics/ML teams), the platform replaces values with tokens, keeping originals in a secured token vault. Deterministic tokenisation is supported where business requires joins/matching without exposing values. Detokenisation is restricted to explicitly authorised roles and purposes, and every detokenisation is audited.

**Why this priority**: Tokenisation enables safe analytics on PII — a headline BRD capability — but builds on classification and key management.

**Independent Test**: Can be tested by tokenising a column, verifying tokens are consistent for the same input (deterministic mode), joins work on tokens, an unauthorised detokenisation attempt is denied and audited, and an authorised one succeeds with an audit record.

**Acceptance Scenarios**:

1. **Given** a column configured for deterministic tokenisation, **When** the same source value appears in multiple batches, **Then** the same token is produced, enabling joins without exposing the value.
2. **Given** a user without detokenisation rights, **When** the user attempts to retrieve original values, **Then** the attempt is denied and recorded in the audit log.
3. **Given** an authorised service detokenising for an approved transformation, **When** detokenisation occurs, **Then** the audit record shows who, what, when, purpose, and result.

---

### User Story 4 - Key management through approved KMS (Priority: P2)

All encryption keys are managed through approved key management services (cloud KMS or an external enterprise KMS) with rotation, versioning, lifecycle management, access control, revocation, and separation of duties. Keys are never stored in application configuration and never exposed through the catalog or UI. The platform presents a logical encryption service so users configure protection without knowing which cloud KMS is underneath.

**Why this priority**: Keys are the foundation of encryption; mismanaged keys void every other control. Depends on the encryption story.

**Independent Test**: Can be tested by configuring key rotation, verifying old key versions still decrypt historical data while new writes use the new version; verifying no key material appears in configuration exports, logs, or UI; and verifying a revoked key blocks further decryption.

**Acceptance Scenarios**:

1. **Given** a configured key rotation schedule, **When** rotation occurs, **Then** new data uses the new key version, historical data remains readable, and the rotation is audited.
2. **Given** any configuration export, log, catalog entry, or UI screen, **When** inspected, **Then** no key material or secret value is present.
3. **Given** a revoked or disabled key, **When** a process attempts decryption with it, **Then** the attempt fails and is audited.
4. **Given** the same logical encryption configuration, **When** the platform runs on either supported cloud, **Then** protection behaviour is identical, with the cloud-specific KMS resolved by the platform.

---

### User Story 5 - Secure access enforcement chain (Priority: P2)

Access to data follows the chain: identity → authentication → authorisation → classification → protection policy → data access. RBAC operates at dataset, table, column, and row level with least-privilege enforcement. Decryption or detokenisation requires permission to use the relevant key or token service in addition to data access rights.

**Why this priority**: Encryption without access control is incomplete (BRD 34M); this story binds security to the platform's identity model.

**Independent Test**: Can be tested with users of different roles querying the same dataset and verifying: row filters apply, column protections differ by role, and key-use permission is separately enforced from data-read permission.

**Acceptance Scenarios**:

1. **Given** a role with row-level restrictions, **When** the user queries a dataset, **Then** only authorised rows return.
2. **Given** a user with dataset read rights but without key-use rights, **When** the user requests decrypted values, **Then** the request is denied; masked/tokenised values still return per policy.
3. **Given** any access decision, **When** audited, **Then** the record shows identity, resource, action, classification consulted, and outcome.

---

### User Story 6 - Security auditability (Priority: P3)

All security-sensitive operations are audited: encryption, decryption, tokenisation, detokenisation, key usage, key rotation, policy changes, restricted-data access, file transfers, failed decryption attempts, and configuration changes. Audit records include timestamp, identity, dataset, column, action, purpose, and result. Audit logs are tamper-evident and searchable by security reviewers.

**Why this priority**: Auditability proves every other control operated; essential for compliance but consumers are reviewers, not daily users.

**Independent Test**: Can be tested by performing a scripted set of security-sensitive operations, then verifying each appears in the audit log with complete fields, and that log tampering attempts are detectable.

**Acceptance Scenarios**:

1. **Given** a detokenisation event, **When** a reviewer searches the audit log, **Then** the record shows user, dataset, column, action, purpose, result, and protection service reference.
2. **Given** a failed decryption attempt, **When** it occurs, **Then** it is recorded and can trigger an alert per configuration.
3. **Given** audit logs, **When** a reviewer queries by time range, identity, dataset, or action type, **Then** matching records return completely.

---

### Edge Cases

- What happens when a source delivers a file encrypted with an unapproved mechanism or unknown key? Ingestion rejects the file to quarantine with "encryption policy violation"; it is never processed or stored in plaintext.
- What happens when a token vault is unavailable during processing? Processing fails closed: the batch is blocked, not written with plaintext values; the failure is recorded and alerted.
- What happens when a classification is lowered (RESTRICTED to INTERNAL)? The policy change requires authorisation, applies to subsequent processing only, is audited, and previously protected data remains protected until reprocessed under the new policy.
- What happens when a key is compromised? Revocation blocks further use; data re-encryption under a new key is an operational procedure the platform supports via key versioning; all usage of the compromised key remains auditable.
- What happens when a user's role changes mid-session? Access decisions reflect current authorisation at query time; no cached grants survive revocation.
- What happens when a downstream export (query download) includes a protected column? Export applies the same protection policy as the UI; raw values never leave through exports unless the exporter holds detokenisation rights, and the export is audited.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST support data classification levels PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED, and HIGHLY RESTRICTED, and MUST allow organisations to define their own classification-to-protection mappings.
- **FR-002**: Protection policy MUST be driven by classification, not chosen ad hoc per pipeline; policy changes MUST propagate automatically to relevant ingestion and transformation processes.
- **FR-003**: System MUST support column-level protection mechanisms: encryption, tokenisation, masking, hashing, redaction, and pseudonymisation; the mechanism per column MUST be policy-driven.
- **FR-004**: All data MUST be encrypted at rest across Bronze, Silver, Gold, metadata, logs containing sensitive data, temporary storage, and backups.
- **FR-005**: All data in transit MUST use encrypted channels; the platform MUST reject unencrypted transfer paths for data flows it controls.
- **FR-006**: System MUST accept files encrypted at the source (industry-standard mechanisms only — no proprietary cryptography), verify integrity, signature, encryption status, and authenticity before processing, and reject non-conforming files to quarantine.
- **FR-007**: System MUST support both platform-managed keys and customer-managed keys.
- **FR-008**: All keys MUST be managed through approved key management services with rotation, versioning, lifecycle management, access control, revocation, and separation of duties; keys MUST NEVER be stored in application configuration or exposed via catalog or UI.
- **FR-009**: Key rotation MUST keep historical data readable via prior key versions while new writes use the current version; rotations MUST be audited.
- **FR-010**: System MUST provide a logical encryption service abstraction: identical logical protection configuration and behaviour on all supported clouds, with cloud-specific key services resolved by the platform.
- **FR-011**: Tokenisation MUST keep original values only in a secured token service; deterministic tokenisation MUST be supported where joins/matching are required.
- **FR-012**: Detokenisation and decryption MUST require explicit authorisation (role plus key/token-use permission) and a recorded purpose; all such operations MUST be audited.
- **FR-013**: Access control MUST enforce the chain identity → authentication → authorisation → classification → protection policy → data access, with RBAC at dataset, table, column, and row level and least-privilege defaults.
- **FR-014**: All security-sensitive operations MUST be audited with timestamp, identity, resource, action, purpose, and result; audit logs MUST be tamper-evident and searchable.
- **FR-015**: Failed decryption/detokenisation attempts MUST be recorded and MUST be alertable.
- **FR-016**: Data exports and downloads MUST enforce the same protection policies as in-platform access; protected values MUST NOT leave through exports without authorised detokenisation, and exports MUST be audited.
- **FR-017**: The catalog MUST display per-column protection metadata (classification, protection mechanism, masking/tokenisation status, authorised roles, key reference identifier) and MUST NEVER display key material.
- **FR-018**: Lineage MUST record protection state transitions (e.g. encrypted at source, protected in Silver, tokenised in Gold) so protection status is traceable end to end.
- **FR-019**: Security failures MUST fail closed: when a protection service is unavailable or a policy cannot be enforced, affected processing MUST block rather than proceed unprotected.
- **FR-020**: Classification downgrades MUST require authorisation, MUST be audited, and MUST NOT retroactively expose already-protected data without reprocessing under the new policy.
- **FR-021**: Private network connectivity MUST be supported for source connections where the source environment provides it, avoiding public-internet transfer of sensitive data.

### Key Entities

- **Classification**: A dataset/column sensitivity level (PUBLIC … HIGHLY RESTRICTED) with the organisation's mapping to a protection policy.
- **Protection Policy**: The enforceable rule set for a classification or specific column: mechanism (encrypt/tokenise/mask/hash/redact/pseudonymise), key or token service reference, authorised roles, detokenisation rules.
- **Key**: A cryptographic key reference in an approved KMS: id, version history, rotation schedule, lifecycle state (active, disabled, revoked), usage permissions. No key material is ever stored by the platform.
- **Token**: A surrogate for a sensitive value held in the token service; deterministic mode maps identical inputs to identical tokens.
- **Security Audit Record**: One security-sensitive event: timestamp, identity, dataset, column, action, purpose, result, protection service reference.
- **Access Decision**: The outcome of the enforcement chain for a request: identity, resource, classification consulted, policy applied, granted/denied.
- **Encryption Metadata**: Per-file/per-batch record of source-side encryption: mechanism, key reference, signature/checksum, verification result.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Zero plaintext sensitive data at rest or in transit anywhere in the platform, verified by security review and automated scanning of storage and transfer configurations.
- **SC-002**: 100% of datasets carrying sensitive columns have classification and an enforced protection policy before reaching CONSUMABLE state.
- **SC-003**: Zero key material or secrets present in any configuration export, log, catalog entry, or UI screen, verified by automated secret scanning in CI/CD.
- **SC-004**: 100% of decryption, detokenisation, and restricted-access operations produce a complete audit record; auditors can retrieve any such event within one minute of search.
- **SC-005**: Unauthorised access attempts (data or key use) are denied 100% of the time and recorded; a penetration-style validation finds no bypass of the enforcement chain.
- **SC-006**: Key rotation completes without data loss or downtime: historical data remains readable and new writes use the rotated key, verified on a production-like environment.
- **SC-007**: The same logical protection configuration produces identical protection behaviour on both supported clouds, verified by a parity test suite.
- **SC-008**: Security controls do not materially reduce authorised consumption: authorised users complete standard query and export tasks with no more than one additional approval step versus unprotected data.

## Assumptions

- Identity federation with the organisation's identity provider and platform RBAC administration are platform capabilities owned by feature 001 (deployment) and the Web UI feature; this feature consumes them for the enforcement chain.
- MVP protection scope follows BRD Phase 1: encryption at rest, in transit, source-side file encryption, basic column protection, key management integration. Advanced tokenisation is BRD Phase 2 — this spec defines the tokenisation behaviour required when enabled; deterministic tokenisation may be delivered in Phase 2.
- AI agents may recommend classifications and protections but MUST NOT retrieve keys, decrypt, detokenise, change policies, grant access, disable encryption, or export protected data without explicit authorisation (constitution Principle V); agent integration itself is Phase 3.
- The specific KMS (AWS KMS, GCP Cloud KMS, or external enterprise KMS) is resolved per deployment; external enterprise KMS support is "considered" per BRD and may follow cloud-native KMS support.
- Source-side encryption agents (the lightweight component deployed near sources) are part of the secure file transfer path; their packaging (container/service) is a planning detail.
- Certificate management for TLS follows cloud/organisational standards; automated certificate rotation is an operational requirement handled at deployment level.
- Row-level security expression language and policy authoring UX are planning details; this spec requires the capability, not the syntax.
