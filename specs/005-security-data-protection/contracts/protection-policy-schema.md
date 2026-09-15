# Contract: Protection Policy Schema

**Feature**: 005-security-data-protection | **Version**: v1 | **Date**: 2026-09-15

Strict Pydantic schema for a protection policy (FR-002, FR-003). Unknown fields rejected. Mechanism is policy-driven, never chosen ad hoc per pipeline.

## Schema

```yaml
name: string                 # unique policy name
classification: enum         # public | internal | confidential | restricted | highly_restricted
mechanism: enum              # encrypt | tokenise | mask | hash | redact | pseudonymise
key_ref_id: uuid | null      # required for encrypt/tokenise
token_service_ref: string | null   # token vault reference (tokenise)
authorised_roles: [string]   # roles allowed to read raw values (FR-012)
detokenise_roles: [string] | null  # roles allowed to detokenise (FR-012)
masking_rule: object | null  # e.g. { "show_first": 1, "show_last": 1 } (mask)
```

## Validation rules

- `classification` MUST be one of the five levels (FR-001).
- `mechanism` MUST be one of the six mechanisms (FR-003).
- `key_ref_id` REQUIRED when `mechanism` is `encrypt` or `tokenise` (FR-008).
- `token_service_ref` REQUIRED when `mechanism` is `tokenise` (FR-011).
- `authorised_roles` MUST be non-empty (least-privilege default, FR-013).
- `detokenise_roles` MUST be a subset of `authorised_roles` when present (FR-012).
- `masking_rule` only valid when `mechanism` is `mask`.
- Secret-scan: any field carrying free text is secret-scanned (SC-003); key material is never accepted.

## Example

```yaml
name: restricted-encrypt
classification: restricted
mechanism: encrypt
key_ref_id: 3f2c9a1e-0000-4000-8000-000000000001
authorised_roles: [data-engineer]
detokenise_roles: [security-officer]
```