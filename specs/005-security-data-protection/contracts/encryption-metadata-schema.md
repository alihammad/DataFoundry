# Contract: Encryption Metadata Schema

**Feature**: 005-security-data-protection | **Version**: v1 | **Date**: 2026-09-15

Per-file/per-batch record of source-side encryption (FR-006). The platform verifies integrity, signature, encryption status, and authenticity before processing; files failing verification are rejected to quarantine and never processed or stored in plaintext.

## Schema

```yaml
batch_id: uuid
file_ref: string            # object-storage path
mechanism: enum             # pgp | gpg | envelope | kms
key_ref_id: uuid | null     # key reference used (never material)
signature: string | null    # signature to verify
checksum: string | null     # integrity checksum
verification_result: enum   # verified | failed | not_verified
verified_at: timestamp | null
```

## Validation rules

- `mechanism` MUST be an industry-standard mechanism (FR-006 — no proprietary cryptography).
- `key_ref_id` MUST reference a registered key (FR-008); key material is never submitted.
- `verification_result` MUST be `verified` before the file is processed.
- A file with `verification_result: failed` or `not_verified` MUST be routed to quarantine with reason "encryption policy violation" (FR-006, Edge Case).
- Secret-scan: `signature`/`checksum` fields are secret-scanned (SC-003).

## Example

```yaml
batch_id: 9f2c1a3e-0000-4000-8000-000000000002
file_ref: s3://bucket/landing/customers.csv.pgp
mechanism: pgp
key_ref_id: 3f2c9a1e-0000-4000-8000-000000000001
signature: "-----BEGIN PGP SIGNATURE-----..."
checksum: sha256:abc123...
verification_result: verified
verified_at: 2026-09-15T10:00:00Z
```