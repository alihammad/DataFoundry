# Tasks: Security and Data Protection

**Input**: Design documents from `/specs/005-security-data-protection/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (security-api.md, protection-policy-schema.md, encryption-metadata-schema.md), quickstart.md

**Tests**: Included — the constitution (Principle IV: Shift-Left Testing & Contracts) and plan.md test plan explicitly mandate contract tests, and quickstart.md defines the test suite map (unit / contract / integration / manual E2E gate).

**Organization**: Tasks are grouped by user story (US1 P1, US2 P1, US3 P2, US4 P2, US5 P2, US6 P3) so each story can be implemented, tested, and delivered independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3, US4, US5, or US6
- Exact file paths included in every task

## Path Conventions

Monorepo per plan.md: `control-plane/src/datafoundry/controlplane/` (FastAPI service), `control-plane/tests/`, `cli/src/datafoundry/cli/`, `terraform/` (provider-isolated modules). This feature extends the existing feature 001/002/004 control plane — no new service or infrastructure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add security dependencies, package skeleton, and shared test harness

- [X] T001 Add security dependencies to `control-plane/pyproject.toml`: `cryptography` (standard primitives for source-side encryption verification + column-level protection in the simulated gateway). Verify `pip install -e ".[dev]"` resolves in `control-plane/.venv`.
- [X] T002 [P] Create the `security` package skeleton per plan.md: `control-plane/src/datafoundry/controlplane/security/` with `__init__.py`, `classification.py`, `policy.py`, `protection.py`, `encryption.py`, `keys.py`, `tokens.py`, `access.py`, `audit.py`, `engine.py`, `gateway.py` — empty module stubs with docstrings.
- [X] T003 [P] Create the `SimulatedSecurityGateway` test harness in `control-plane/src/datafoundry/controlplane/security/gateway.py`: in-memory fake KMS (key references + versions + lifecycle), token vault (deterministic + random), protection engine (encrypt/tokenise/mask/hash/redact/pseudonymise), source-encryption fixtures, with fault-injection hooks (`force_kms_unavailable`, `force_token_vault_unavailable`, `force_verification_failure`) so every classification/protection/tokenisation/key/access/audit path is exercisable offline — no docker/terraform/database required.
- [X] T004 [P] Extend `control-plane/tests/conftest.py` with security fixtures: a `simulated_security_gateway` fixture, a `classified_dataset` fixture (reuse feature 003 dataset helper or a minimal stub), and a `process_security_run` fixture that drives the security engine synchronously (mirroring the feature 001 `process_run` pattern).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core security models, schema, protection engine, and audit primitives that every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 Implement the seven security SQLAlchemy models per data-model.md — `Classification`, `ProtectionPolicy`, `KeyReference`, `TokenReference`, `SecurityAuditRecord`, `AccessDecision`, `EncryptionMetadata` — in `control-plane/src/datafoundry/controlplane/db/models.py`, including: unique `name` on ProtectionPolicy, JSONB columns via the existing `with_variant` pattern, and the tamper-evident hash chain on SecurityAuditRecord.
- [X] T006 Create the Alembic migration for the seven new tables (revoke UPDATE/DELETE on the append-only SecurityAuditRecord; reuse feature 001 migration conventions) — in `control-plane/src/datafoundry/controlplane/db/migrations/`. Verify offline SQL via `alembic upgrade head --sql`.
- [X] T007 [P] Implement the protection policy Pydantic schema per contracts/protection-policy-schema.md (strict, unknown fields rejected; classification/mechanism enums; key_ref required for encrypt/tokenise; detokenise_roles subset of authorised_roles; secret-scan) — in `control-plane/src/datafoundry/controlplane/config/security_schema.py`.
- [X] T008 [P] Implement the classification module per research R-06: `Classification` model, level enum (PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED/HIGHLY_RESTRICTED), org-defined classification→policy mapping, downgrade authorisation (FR-020) — in `control-plane/src/datafoundry/controlplane/security/classification.py`.
- [X] T009 [P] Implement the protection policy resolution per research R-02: map a classification to an enforceable policy; mechanism per column is policy-driven, never ad hoc (FR-002) — in `control-plane/src/datafoundry/controlplane/security/policy.py`.
- [X] T010 [P] Implement the column-level protection engine per research R-02: registry of six mechanisms (encrypt/tokenise/mask/hash/redact/pseudonymise), each returning protected value + status (R-02) — in `control-plane/src/datafoundry/controlplane/security/protection.py`.
- [X] T011 [P] Implement the logical encryption service per research R-01: key reference model, rotation/versioning/revocation, keys never stored or exposed (FR-008, FR-009, FR-010) — in `control-plane/src/datafoundry/controlplane/security/keys.py`.
- [X] T012 [P] Implement the token service per research R-02: deterministic + random tokenisation, originals only in the secured token service (FR-011), detokenisation requires authorisation + purpose (FR-012) — in `control-plane/src/datafoundry/controlplane/security/tokens.py`.
- [X] T013 [P] Implement the access enforcement chain per research R-04: identity → authentication → authorisation → classification → protection policy → data access; RBAC at dataset/table/column/row level; key-use permission separate from data-read (FR-013) — in `control-plane/src/datafoundry/controlplane/security/access.py`.
- [X] T014 [P] Implement the security audit module per research R-05: tamper-evident chained-hash SecurityAuditRecord, searchable by time/identity/dataset/action (FR-014), failed decryption/detokenisation recorded + alertable (FR-015) — in `control-plane/src/datafoundry/controlplane/security/audit.py`.
- [X] T015 [P] Wire secret-scan (feature 001 `config/secret_scan.py`) into every security write/export path: policy `name`, key `key_id`, token `value`, audit `purpose` (SC-003) — in `control-plane/src/datafoundry/controlplane/security/` and `config/security_schema.py`.
- [X] T016 [P] Add security audit actions to the existing audit service (feature 001 `audit/service.py`): `security.encrypt`, `security.decrypt`, `security.tokenise`, `security.detokenise`, `security.key_rotate`, `security.key_revoke`, `security.policy_change`, `security.restricted_access`, `security.failed_decrypt` — each secret-scanned (FR-014, SC-003).
- [X] T017 [P] Unit tests for foundational core: protection policy schema conformance vs protection-policy-schema.md, classification mapping + downgrade authorisation, protection mechanism registry, key rotation/revocation, tokenisation determinism, access chain, and audit hash-chain tamper detection — in `control-plane/tests/unit/test_security_core.py`.

**Checkpoint**: Foundation ready — user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Classification-driven data protection (Priority: P1) 🎯 MVP

**Goal**: A data owner classifies a dataset (PUBLIC … HIGHLY RESTRICTED) and the platform maps the classification to an enforceable protection policy. Sensitive columns are identified and protected per policy — encryption, tokenisation, masking, hashing, redaction, or pseudonymisation — without the data engineer choosing mechanisms by hand. Organisations can define their own classification-to-protection mappings.

**Independent Test**: quickstart Scenario 1 — classify a dataset RESTRICTED with a sensitive email column, ingest data, verify the column is protected per the mapped policy in all layers while non-sensitive columns remain queryable.

### Tests for User Story 1 ⚠️ (write first, ensure they FAIL before implementation)

- [X] T018 [P] [US1] Contract tests for `POST /datasets/{id}/classification` (201 with classification_id/level/policy_id; 422 invalid level/unknown policy; 403 unauthorised downgrade), `GET /datasets/{id}/classification` (level + per-column protection metadata, never key material) per contracts/security-api.md §1 — in `control-plane/tests/contract/test_classification_api.py`
- [X] T019 [P] [US1] Integration test for quickstart Scenario 1: classify RESTRICTED with sensitive email column, ingest, verify email protected per policy in Bronze/Silver/Gold while non-sensitive columns queryable — in `control-plane/tests/integration/test_classification_protection_flow.py`

### Implementation for User Story 1

- [X] T020 [P] [US1] Implement the classification API router per contracts/security-api.md §1: `POST /datasets/{id}/classification`, `GET /datasets/{id}/classification`; downgrade authorisation (FR-020); audit writes — in `control-plane/src/datafoundry/controlplane/api/classification.py`
- [X] T021 [P] [US1] Implement the protection policy API router per contracts/security-api.md §2: `POST /policies`, `GET /policies`; secret-scan on `name`; audit writes — in `control-plane/src/datafoundry/controlplane/api/protection.py`
- [X] T022 [US1] Implement CLI `datafoundry classify set/get` and `datafoundry protect apply/export` commands per quickstart Scenario 1 — in `cli/src/datafoundry/cli/commands/classify.py` and `cli/src/datafoundry/cli/commands/protect.py`

**Checkpoint**: US1 fully functional — classification drives protection policy with per-column protection metadata in the catalog

---

## Phase 4: User Story 2 - Encryption in depth (Priority: P1)

**Goal**: All data is encrypted at rest (every layer, metadata, logs, temporary and backup storage) and in transit (all transfers use encrypted channels). Files containing sensitive data can be encrypted at the source before transmission; the platform accepts pre-encrypted files, verifies their integrity and authenticity, and processes them per policy. Both platform-managed and customer-managed keys are supported.

**Independent Test**: quickstart Scenario 2 — verify storage-level encryption is enabled on all zones; a plaintext transfer attempt is rejected; a source-encrypted file is accepted, verified, and processed; and a customer-managed key configuration works end to end.

### Tests for User Story 2 ⚠️

- [X] T023 [P] [US2] Contract tests for `POST /keys` (201 key_ref_id/version; 422 invalid kms/missing key_id/secret-scan hit), `POST /keys/{id}/rotate` (200 version++), `POST /keys/{id}/revoke` (200 revoked), `GET /keys/{id}` (status, never material) per contracts/security-api.md §3 — in `control-plane/tests/contract/test_keys_api.py`
- [X] T024 [P] [US2] Integration test for quickstart Scenario 2: verify storage encryption on all zones, reject plaintext transfer, accept + verify + process a source-encrypted file, customer-managed key end to end — in `control-plane/tests/integration/test_encryption_in_depth_flow.py`

### Implementation for User Story 2

- [X] T025 [P] [US2] Implement the keys API router per contracts/security-api.md §3: `POST /keys`, `POST /keys/{id}/rotate`, `POST /keys/{id}/revoke`, `GET /keys/{id}`; keys never stored or exposed (FR-008); audit writes — in `control-plane/src/datafoundry/controlplane/api/keys.py`
- [X] T026 [P] [US2] Implement source-side encryption verification per research R-03: verify integrity/signature/encryption status/authenticity before processing; reject non-conforming files to quarantine (FR-006) — in `control-plane/src/datafoundry/controlplane/security/encryption.py`
- [X] T027 [US2] Implement CLI `datafoundry key register/rotate/revoke/status` commands per quickstart Scenario 2 — in `cli/src/datafoundry/cli/commands/key.py`

**Checkpoint**: US1 + US2 both work independently — classification-driven protection and encryption in depth with source-side verification

---

## Phase 5: User Story 3 - Tokenisation of highly sensitive values (Priority: P2)

**Goal**: For highly sensitive attributes (PII consumed by analytics/ML teams), the platform replaces values with tokens, keeping originals in a secured token vault. Deterministic tokenisation is supported where business requires joins/matching without exposing values. Detokenisation is restricted to explicitly authorised roles and purposes, and every detokenisation is audited.

**Independent Test**: quickstart Scenario 3 — tokenise a column, verify tokens are consistent for the same input (deterministic mode), joins work on tokens, an unauthorised detokenisation attempt is denied and audited, and an authorised one succeeds with an audit record.

### Tests for User Story 3 ⚠️

- [ ] T028 [P] [US3] Contract tests for `POST /datasets/{id}/tokens/tokenise` (200 token; deterministic same-input-same-token; 403 unauthorised), `POST /datasets/{id}/tokens/detokenise` (200 value + audited; 403 unauthorised + recorded) per contracts/security-api.md §4 — in `control-plane/tests/contract/test_tokens_api.py`
- [ ] T029 [P] [US3] Integration test for quickstart Scenario 3: tokenise column, verify deterministic tokens + joins work, unauthorised detokenisation denied + audited, authorised detokenisation succeeds with audit — in `control-plane/tests/integration/test_tokenisation_flow.py`

### Implementation for User Story 3

- [ ] T030 [P] [US3] Implement the tokens API router per contracts/security-api.md §4: `POST /datasets/{id}/tokens/tokenise`, `POST /datasets/{id}/tokens/detokenise`; detokenisation authorisation + purpose (FR-012); audit writes — in `control-plane/src/datafoundry/controlplane/api/tokens.py`
- [ ] T031 [US3] Implement CLI `datafoundry token tokenise/detokenise` commands per quickstart Scenario 3 — in `cli/src/datafoundry/cli/commands/token.py`

**Checkpoint**: US1 + US2 + US3 all work independently — classification, encryption, and tokenisation with audited detokenisation

---

## Phase 6: User Story 4 - Key management through approved KMS (Priority: P2)

**Goal**: All encryption keys are managed through approved key management services with rotation, versioning, lifecycle management, access control, revocation, and separation of duties. Keys are never stored in application configuration and never exposed through the catalog or UI. The platform presents a logical encryption service so users configure protection without knowing which cloud KMS is underneath.

**Independent Test**: quickstart Scenario 4 — configure key rotation, verify old key versions still decrypt historical data while new writes use the new version; verify no key material appears in configuration exports, logs, or UI; and verify a revoked key blocks further decryption.

### Tests for User Story 4 ⚠️

- [ ] T032 [P] [US4] Contract tests for key rotation/revocation lifecycle: rotate keeps historical data readable via prior versions while new writes use current (FR-009); revoked key blocks decryption + audited (FR-008); no key material in any export/log/UI (SC-003) per contracts/security-api.md §3 — in `control-plane/tests/contract/test_keys_api.py`
- [ ] T033 [P] [US4] Integration test for quickstart Scenario 4: rotate key, verify old versions decrypt historical data + new writes use new version; revoke key, verify decryption fails + audited; verify no key material in exports — in `control-plane/tests/integration/test_key_rotation_flow.py`

### Implementation for User Story 4

- [ ] T034 [P] [US4] Implement key lifecycle in the logical encryption service: rotation keeps historical data readable via prior versions (FR-009), revocation blocks further decryption (FR-008), separation of duties (FR-008) — in `control-plane/src/datafoundry/controlplane/security/keys.py`
- [ ] T035 [US4] Implement cloud-independence of key behaviour (FR-010, SC-007): identical logical protection behaviour on both clouds, cloud-specific KMS resolved by the platform — extend `scripts/parity_checklist.py` with a security parity check (mirroring feature 002 SC-003 pattern)

**Checkpoint**: US1–US4 all work — keys are managed through KMS with rotation/versioning/revocation and cloud-independent behaviour

---

## Phase 7: User Story 5 - Secure access enforcement chain (Priority: P2)

**Goal**: Access to data follows the chain: identity → authentication → authorisation → classification → protection policy → data access. RBAC operates at dataset, table, column, and row level with least-privilege enforcement. Decryption or detokenisation requires permission to use the relevant key or token service in addition to data access rights.

**Independent Test**: quickstart Scenario 5 — users of different roles query the same dataset and verify: row filters apply, column protections differ by role, and key-use permission is separately enforced from data-read permission.

### Tests for User Story 5 ⚠️

- [ ] T036 [P] [US5] Contract tests for `POST /access/decide` (200 outcome granted/denied with classification_consulted/policy_applied/reason; key-use permission separately enforced from data-read) per contracts/security-api.md §5 — in `control-plane/tests/contract/test_access_api.py`
- [ ] T037 [P] [US5] Integration test for quickstart Scenario 5: users of different roles query same dataset, verify row filters apply, column protections differ by role, key-use permission separately enforced — in `control-plane/tests/integration/test_access_enforcement_flow.py`

### Implementation for User Story 5

- [ ] T038 [P] [US5] Implement the access API router per contracts/security-api.md §5: `POST /access/decide`; evaluate enforcement chain at query time (no cached grants); audit writes — in `control-plane/src/datafoundry/controlplane/api/access.py`
- [ ] T039 [US5] Implement CLI `datafoundry access decide` command per quickstart Scenario 5 — in `cli/src/datafoundry/cli/commands/access.py`

**Checkpoint**: US1–US5 all work — access follows the enforcement chain with least-privilege and separate key-use permission

---

## Phase 8: User Story 6 - Security auditability (Priority: P3)

**Goal**: All security-sensitive operations are audited: encryption, decryption, tokenisation, detokenisation, key usage, key rotation, policy changes, restricted-data access, file transfers, failed decryption attempts, and configuration changes. Audit records include timestamp, identity, dataset, column, action, purpose, and result. Audit logs are tamper-evident and searchable by security reviewers.

**Independent Test**: quickstart Scenario 6 — perform a scripted set of security-sensitive operations, then verify each appears in the audit log with complete fields, and that log tampering attempts are detectable.

### Tests for User Story 6 ⚠️

- [ ] T040 [P] [US6] Contract tests for `GET /security-audit` (search by identity/dataset/action/date range), `GET /security-audit/{id}` (full record incl. prev_hash/hash for tamper verification) per contracts/security-api.md §6 — in `control-plane/tests/contract/test_security_audit_api.py`
- [ ] T041 [P] [US6] Integration test for quickstart Scenario 6: perform scripted security operations, verify each appears with complete fields, verify tampering detectable — in `control-plane/tests/integration/test_security_audit_flow.py`

### Implementation for User Story 6

- [ ] T042 [P] [US6] Implement the security audit API router per contracts/security-api.md §6: `GET /security-audit`, `GET /security-audit/{id}`; tamper-evident hash chain (FR-014); failed decryption/detokenisation alertable (FR-015) — in `control-plane/src/datafoundry/controlplane/api/security_audit.py`
- [ ] T043 [US6] Implement CLI `datafoundry security-audit search/get` commands per quickstart Scenario 6 — in `cli/src/datafoundry/cli/commands/security_audit.py`

**Checkpoint**: US1–US6 all work — security is auditable with tamper-evident, searchable records

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Protection metadata & lineage, fail-closed enforcement, cloud-independence verification, and final validation

- [ ] T044 [P] Implement protection metadata + lineage per research R-07: catalog displays per-column protection metadata (classification, mechanism, masking/tokenisation status, authorised roles, key reference identifier) and never key material (FR-017); lineage records protection state transitions (FR-018) — in `control-plane/src/datafoundry/controlplane/security/` and `api/classification.py`
- [ ] T045 [P] Implement fail-closed enforcement per research R-06: when a protection service is unavailable or a policy cannot be enforced, affected processing blocks rather than proceeding unprotected (FR-019); classification downgrades never retroactively expose protected data (FR-020) — in `control-plane/src/datafoundry/controlplane/security/engine.py`
- [ ] T046 [P] Implement alerting on security failures per research R-05: failed decryption/detokenisation attempts and restricted-access denials fire structured alerts through the platform's notification channels (FR-015), redacted of secrets — in `control-plane/src/datafoundry/controlplane/security/` (reuse observability/audit)
- [ ] T047 [P] Verify cloud-independence of protection behaviour (FR-010, SC-007): identical protection outcomes for identical data/config on both clouds — extend `scripts/parity_checklist.py` with a security parity check (mirroring feature 002 SC-003 pattern)
- [ ] T048 [P] Run full test suite + ruff clean: `control-plane/.venv/bin/python -m pytest` (all unit + contract + integration) and `ruff check` + `ruff format` clean across control-plane + cli; verify `alembic upgrade head --sql` offline SQL — final gate.

**Checkpoint (Final)**: Feature 005 complete — all 6 user stories independently testable, ruff clean, tests pass, cloud-independent protection behaviour verified