# Quickstart: Security and Data Protection

**Feature**: 005-security-data-protection | **Date**: 2026-09-15

Runnable validation scenarios proving the feature works end to end. Prerequisites: control plane running (feature 001), CLI installed, simulated security gateway (default in dev/tests — no docker/terraform/database required).

## Prerequisites

- Control plane up: `uvicorn datafoundry.controlplane.api.app:app`
- CLI: `datafoundry --help` (shows `classify`, `protect`, `key`, `token`, `security-audit` groups)
- Simulated security gateway active (dev mode default)

## Scenario 1: Classification-driven protection (US1, FR-001/002/003, FR-017)

Classify a dataset RESTRICTED with a sensitive email column, then verify the column is protected per the mapped policy in all layers while non-sensitive columns remain queryable.

```bash
datafoundry classify set <dataset_id> --level restricted
datafoundry protect apply <dataset_id> --column email
datafoundry classify get <dataset_id>
```

**Expected**: `classify get` shows `level: restricted`, the email column with `mechanism: encrypt` (or the org-mapped mechanism), `masking_status`, `authorised_roles`, and a `key_ref_id` — never key material (FR-017, SC-003). Non-sensitive columns carry no protection.

## Scenario 2: Encryption in depth (US2, FR-004/005/006/007)

Verify storage-level encryption is enabled on all zones, a plaintext transfer attempt is rejected, and a source-encrypted file is accepted, verified, and processed.

```bash
datafoundry key register --kms aws_kms --key-id alias/restricted
datafoundry key status <key_ref_id>
# ingest a source-encrypted file with encryption metadata
datafoundry ingest --file customers.csv.pgp --encryption-meta meta.json
```

**Expected**: `key status` shows the key reference (never material). A source-encrypted file with valid metadata is verified (`verification_result: verified`) and processed; a file failing verification is rejected to quarantine with "encryption policy violation" and never stored in plaintext (FR-006).

## Scenario 3: Tokenisation (US3, FR-011/012)

Tokenise a column, verify deterministic tokens are consistent, and that an unauthorised detokenisation is denied and audited while an authorised one succeeds.

```bash
datafoundry token tokenise <dataset_id> --column email --value a@x.com --deterministic
datafoundry token tokenise <dataset_id> --column email --value a@x.com --deterministic
datafoundry token detokenise <dataset_id> --column email --token tok_abc123 --purpose approved-analytics
```

**Expected**: both tokenise calls return the same token (deterministic, FR-011). Detokenisation without the `detokenise_roles` right returns `403` and is recorded (FR-015); with the right and a purpose it returns the value and is audited (FR-012).

## Scenario 4: Key rotation & revocation (US4, FR-008/009)

Rotate a key, verify old versions still decrypt historical data while new writes use the new version, and that a revoked key blocks further decryption.

```bash
datafoundry key rotate <key_ref_id>
datafoundry key revoke <key_ref_id>
datafoundry key status <key_ref_id>
```

**Expected**: after rotation, `version` increments and historical data remains readable (FR-009). After revocation, `lifecycle_state: revoked` and further decryption fails and is audited (FR-008).

## Scenario 5: Access enforcement chain (US5, FR-013)

Users of different roles query the same dataset; verify row filters apply, column protections differ by role, and key-use permission is separately enforced from data-read.

```bash
datafoundry access decide --identity analyst@acme.com --resource "dataset:<id>:column:email" --action read
datafoundry access decide --identity security-officer@acme.com --resource "dataset:<id>:column:email" --action read
```

**Expected**: the analyst gets masked/tokenised values (or denial) per policy; the security-officer with key-use permission gets raw values. Access decisions reflect current authorisation at query time — no cached grants (spec Edge Cases).

## Scenario 6: Security auditability (US6, FR-014/015)

Perform a scripted set of security-sensitive operations, then verify each appears in the audit log with complete fields and that tampering is detectable.

```bash
datafoundry security-audit search --identity user@acme.com
datafoundry security-audit search --action detokenise
datafoundry security-audit get <audit_id>
```

**Expected**: each operation appears with timestamp, identity, dataset, column, action, purpose, result, and protection service reference (FR-014). `security-audit get` shows the chained `prev_hash`/`hash` so tampering is detectable (US6-AC1). Failed decryption/detokenisation attempts are recorded and alertable (FR-015).