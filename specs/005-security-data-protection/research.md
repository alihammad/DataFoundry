# Phase 0 Research: Security and Data Protection

**Feature**: 005-security-data-protection | **Date**: 2026-09-15

All Technical Context unknowns resolved. Format: Decision / Rationale / Alternatives considered.

## R-01: Key management — cloud KMS behind a logical encryption service

**Decision**: Provide a **logical encryption service** abstraction in the control plane that resolves to the deployment's cloud KMS (AWS KMS / GCP Cloud KMS). The platform stores only **key references** (id, version, lifecycle state, usage permissions) in its DB; actual key material lives exclusively in the KMS and is never persisted, logged, or exposed via catalog/UI (FR-008, SC-003). Rotation, versioning, lifecycle, revocation, and access control are delegated to the KMS; the platform records key-usage audit events.

**Rationale**:
- Constitution Security requirements mandate keys through approved KMS with rotation/versioning/lifecycle/access auditing, and forbid keys in application configuration or catalog/UI exposure.
- A logical abstraction (FR-010) keeps protection configuration cloud-free (Principle I) and gives identical behaviour on both clouds (SC-007), with the cloud-specific KMS resolved by the platform.
- Storing only references (not material) makes secret-scanning trivially satisfiable and avoids the platform becoming a key store.

**Alternatives considered**:
- *Store keys in the control-plane DB*: violates FR-008 and SC-003; rejected.
- *Direct cloud-SDK calls in business logic*: breaks cloud-independence (Principle I); rejected — the gateway pattern (feature 001/002) is reused.
- *External enterprise KMS as the only option*: spec Assumptions mark external enterprise KMS as "considered" and possibly later; MVP targets cloud-native KMS behind the same abstraction.

## R-02: Column-level protection mechanisms — registry + policy-driven

**Decision**: Implement the six protection mechanisms (encrypt, tokenise, mask, hash, redact, pseudonymise) as a **registry** (mirrors the capability registry and feature 002 connector registry). The mechanism per column is chosen by the **protection policy** resolved from the dataset's classification (FR-001/002/003), never ad hoc per pipeline. The simulated gateway provides in-memory implementations; live adapters use cloud primitives (KMS-backed encryption, token vault).

**Rationale**:
- Policy-driven (not hand-picked) protection is a constitutional requirement (FR-002); a registry makes adding a mechanism a one-module change (Principle I, FR-015 spirit).
- Deterministic tokenisation (FR-011) is a distinct mode of the tokenise mechanism, keeping joins/matching possible without exposing values.
- Standard cryptography only (FR-006 — no proprietary crypto); `cryptography` primitives for the simulated path.

**Alternatives considered**:
- *Hard-coded per-column mechanism selection*: violates FR-002 (policy-driven); rejected.
- *Single mandated mechanism (e.g. only encryption)*: violates FR-003 (six mechanisms required); rejected.

## R-03: Source-side file encryption verification

**Decision**: At ingestion, the platform verifies a source-encrypted file's **integrity, signature, encryption status, and authenticity** before processing (FR-006). Files failing verification are rejected to quarantine with an "encryption policy violation" reason and are never processed or stored in plaintext (spec Edge Cases). Verification uses industry-standard mechanisms (PGP/GPG, envelope encryption, KMS) only.

**Rationale**:
- "Encryption by default" and "quarantine rather than propagate" are constitutional non-negotiables; a file that cannot be verified must not enter the pipeline.
- Reusing the feature 002 quarantine routing keeps the failure path consistent with the rest of the platform.

**Alternatives considered**:
- *Process unverified files*: violates FR-006 and the Edge Case; rejected.
- *Store unverified files in plaintext for later review*: violates FR-004 (encryption at rest) and the Edge Case; rejected.

## R-04: Access enforcement chain

**Decision**: Enforce the chain identity → authentication → authorisation → classification → protection policy → data access (FR-013) as a single access-decision function. RBAC operates at dataset, table, column, and row level with least-privilege defaults. Decryption/detokenisation requires **key/token-use permission in addition to** data-read permission (FR-012). Access decisions are evaluated at query time — no cached grants survive role changes (spec Edge Cases).

**Rationale**:
- Binds security to the platform's identity model (feature 001) and classification model (this feature), satisfying FR-013 and the "no cached grants" Edge Case.
- Separating data-read from key-use permission (FR-012) is the mechanism that lets masked/tokenised values return while raw values stay protected.

**Alternatives considered**:
- *Single coarse permission*: cannot express column/row-level or key-use separation (FR-012/013); rejected.
- *Cached grants*: violates the role-change Edge Case; rejected.

## R-05: Security auditability — tamper-evident, searchable

**Decision**: All security-sensitive operations (encryption, decryption, tokenisation, detokenisation, key usage, key rotation, policy changes, restricted-data access, file transfers, failed decryption attempts, configuration changes) write a **SecurityAuditRecord** with timestamp, identity, dataset, column, action, purpose, and result (FR-014). Records are tamper-evident (chained hash over prior record) and searchable by time range, identity, dataset, or action type (US6-AC3). Failed decryption/detokenisation attempts are recorded and alertable (FR-015).

**Rationale**:
- Auditability proves every other control operated (US6); the chained hash makes tampering detectable (US6-AC1).
- Reusing the feature 001 audit service's append-only pattern and adding a hash chain satisfies FR-014 without a new store.

**Alternatives considered**:
- *Plain append-only log without hash chain*: not tamper-evident (US6-AC1); rejected.
- *External audit store*: over-provisioned for MVP; the control-plane DB with a hash chain suffices.

## R-06: Classification downgrades & fail-closed

**Decision**: Classification downgrades require authorisation, are audited, apply to subsequent processing only, and never retroactively expose already-protected data without reprocessing under the new policy (FR-020). When a protection service is unavailable or a policy cannot be enforced, affected processing **fails closed** — the batch is blocked, not written unprotected (FR-019, spec Edge Cases).

**Rationale**:
- Directly implements FR-020 and the "classification lowered" Edge Case.
- Fail-closed is a constitutional non-negotiable (FR-019); an unenforceable policy must block rather than silently drop protection.

**Alternatives considered**:
- *Fail-open on protection-service unavailability*: explicitly forbidden by FR-019 and the token-vault Edge Case; rejected.
- *Retroactive exposure on downgrade*: violates FR-020; rejected.

## R-07: Protection metadata & lineage

**Decision**: The catalog displays per-column protection metadata (classification, protection mechanism, masking/tokenisation status, authorised roles, key reference identifier) and never key material (FR-017). Lineage records protection state transitions (e.g. encrypted at source, protected in Silver, tokenised in Gold) so protection status is traceable end to end (FR-018).

**Rationale**:
- FR-017/FR-018 make protection observable and auditable, satisfying the "catalog shows protection status" acceptance scenario (US1-AC1) and the lineage requirement.
- Key reference identifiers (not material) keep SC-003 satisfied.

**Alternatives considered**:
- *No protection metadata in catalog*: violates FR-017 and US1-AC1; rejected.
- *Expose key material in catalog*: violates FR-008/SC-003; rejected.