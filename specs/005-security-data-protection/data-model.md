# Data Model: Security and Data Protection

**Feature**: 005-security-data-protection | **Date**: 2026-09-15

Entities per spec Key Entities + research R-01/R-05/R-07. All control-plane metadata lives in the same PostgreSQL 15 DB as feature 001/002/004 (reuses `db/` models + Alembic; new migration). Key material is NEVER stored — only references.

## Classification

A dataset/column sensitivity level with the organisation's mapping to a protection policy.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| dataset_id | UUID | FK → Dataset | |
| level | enum | PUBLIC / INTERNAL / CONFIDENTIAL / RESTRICTED / HIGHLY_RESTRICTED | FR-001 |
| column | string | nullable; null = dataset-level | |
| policy_id | UUID | FK → ProtectionPolicy | resolved mapping |
| changed_by | string | required | authorisation (FR-020) |
| changed_at | timestamptz | required | |
| previous_level | enum | nullable | audit of downgrade (FR-020) |

**Rules**: classification drives protection policy (FR-002); downgrades require authorisation, are audited, apply to subsequent processing only (FR-020).

## ProtectionPolicy

The enforceable rule set for a classification or specific column.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| name | string | unique | |
| classification | enum | required | PUBLIC … HIGHLY_RESTRICTED |
| mechanism | enum | encrypt / tokenise / mask / hash / redact / pseudonymise | FR-003 |
| key_ref_id | UUID | FK → KeyReference | nullable; for encrypt/tokenise |
| token_service_ref | string | nullable | token vault reference |
| authorised_roles | jsonb | required | roles allowed to read raw (FR-012) |
| detokenise_roles | jsonb | nullable | roles allowed to detokenise (FR-012) |
| masking_rule | jsonb | nullable | e.g. show first/last N chars |
| created_by | string | required | |
| created_at | timestamptz | required | |

**Rules**: mechanism is policy-driven, never ad hoc per pipeline (FR-002); policy changes propagate to relevant ingestion/transformation processes (FR-002).

## KeyReference

A cryptographic key reference in an approved KMS. No key material is ever stored.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| kms | enum | aws_kms / gcp_cloud_kms | FR-010 |
| key_id | string | required | KMS key id (not material) |
| version | int | required | FR-009 |
| lifecycle_state | enum | active / disabled / revoked | FR-008 |
| rotation_schedule | string | nullable | FR-009 |
| usage_permissions | jsonb | required | roles allowed to use (FR-012) |
| created_at | timestamptz | required | |

**Rules**: keys never stored in application configuration or exposed via catalog/UI (FR-008, SC-003); rotation keeps historical data readable via prior versions while new writes use current (FR-009); revoked key blocks further decryption (FR-008).

## TokenReference

A surrogate for a sensitive value held in the token service.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| dataset_id | UUID | FK → Dataset | |
| column | string | required | |
| token | string | required | surrogate value |
| original_hash | string | required | lookup key (never the raw value) |
| deterministic | bool | default false | FR-011 |
| token_service_ref | string | required | vault reference |
| created_at | timestamptz | required | |

**Rules**: originals kept only in the secured token service (FR-011); deterministic mode maps identical inputs to identical tokens (FR-011).

## SecurityAuditRecord

One security-sensitive event (FR-014).

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| occurred_at | timestamptz | required | |
| identity | string | required | |
| dataset_id | UUID | nullable | |
| column | string | nullable | |
| action | string | required | encrypt/decrypt/tokenise/detokenise/key_use/key_rotate/policy_change/restricted_access/file_transfer/failed_decrypt/config_change |
| purpose | string | nullable | FR-012 |
| result | enum | success / denied / failed | FR-014 |
| protection_service_ref | string | nullable | FR-014 |
| prev_hash | string | nullable | tamper-evident chain (R-05) |
| hash | string | required | chained hash (R-05) |

**Rules**: append-only; tamper-evident via chained hash (US6-AC1); searchable by time range, identity, dataset, action (US6-AC3); failed decryption/detokenisation recorded + alertable (FR-015).

## AccessDecision

The outcome of the enforcement chain for a request (FR-013).

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| identity | string | required | |
| resource | string | required | dataset/table/column/row |
| classification_consulted | enum | required | |
| policy_applied | UUID | FK → ProtectionPolicy | |
| outcome | enum | granted / denied | |
| reason | string | nullable | |
| decided_at | timestamptz | required | |

**Rules**: evaluated at query time — no cached grants survive role changes (spec Edge Cases); key-use permission separately enforced from data-read (FR-012).

## EncryptionMetadata

Per-file/per-batch record of source-side encryption (FR-006).

| Field | Type | Constraints | Notes |
|---|---|---|---|
| id | UUID | PK | |
| batch_id | UUID | required | |
| file_ref | string | required | |
| mechanism | string | required | PGP/GPG/envelope/KMS |
| key_ref_id | UUID | FK → KeyReference | nullable |
| signature | string | nullable | |
| checksum | string | nullable | |
| verification_result | enum | verified / failed / not_verified | FR-006 |
| verified_at | timestamptz | nullable | |

**Rules**: files failing verification rejected to quarantine, never processed or stored in plaintext (FR-006, Edge Case).