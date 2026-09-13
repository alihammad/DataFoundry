# Quickstart: Validating One-Click Platform Deployment

**Feature**: 001-one-click-platform-deployment | **Date**: 2026-09-13

Runnable validation scenarios proving the feature works end-to-end. References: [contracts/deployment-api.md](./contracts/deployment-api.md), [contracts/platform-config-schema.md](./contracts/platform-config-schema.md), [contracts/capability-catalog.md](./contracts/capability-catalog.md), [data-model.md](./data-model.md).

---

## Prerequisites

- Docker + Docker Compose
- Python 3.12, `uv` or `pip`
- Terraform CLI >= 1.9 (pinned via `tfenv`/`.terraform-version`)
- For cloud scenarios: an AWS sandbox account or GCP project with deploy permissions; for offline scenarios: LocalStack (AWS emulation)
- Control-plane bootstrap completed once per cloud (see `docs/runbooks/bootstrap.md`): `terraform/control-plane/{aws|gcp}` applied, giving you the API endpoint and admin identity

## Setup (local development)

```bash
# 1. Install control plane + CLI
cd control-plane && uv sync && cd ../cli && uv sync

# 2. Start local dependencies (PostgreSQL, LocalStack)
docker compose -f docker/docker-compose.dev.yml up -d

# 3. Run migrations
uv run alembic upgrade head

# 4. Start the API
uv run uvicorn datafoundry.controlplane.api.app:app --reload --port 8000

# 5. Sanity: liveness
curl -s http://localhost:8000/healthz
# Expected: {"status":"ok","version":"..."}
```

---

## Scenario 1: Validation rejects bad configs before provisioning (SC-004, FR-003)

```bash
datafoundry validate --config platform-configs/examples/bad-config.yaml
# Config enables semantic_layer without catalog, uses an unsupported region,
# and omits approval for production.
```

**Expected**: exit code 1; **all three** errors reported in one response, each with `path`, `code`, `message`, `remediation`. No platform, run, or cloud resource created (verify: `GET /platforms` unchanged; LocalStack resource list empty).

Also via API: `POST /api/v1/validate` returns `422` with the same all-errors body.

## Scenario 2: One-click deploy on emulated AWS (US1, FR-001, FR-016)

```bash
datafoundry deploy --config platform-configs/examples/dev-aws-localstack.yaml
```

**Expected**:
1. `202` with `platform_id` + `run_id`; CLI streams step progress.
2. `GET /api/v1/runs/{run_id}` shows the canonical step order (validate-config → generate-tf → … → health-checks) with per-step statuses; disabled capabilities appear as `skipped`.
3. Run reaches `succeeded`; platform status becomes `ready`; all health checks for enabled capabilities `healthy`.
4. Bronze/Silver/Gold zone prefixes exist in the platform bucket; catalog lists the zones (FR-005).
5. Total wall time recorded in the run < 30 min (LocalStack runs are much faster; the 30-min budget is verified in sandbox accounts — Scenario 6).

## Scenario 3: Progress visibility & failure handling (FR-008, FR-009, SC-005)

```bash
# Force a mid-deployment failure (config points at a quota-exceeded module
# via fault-injection flag in dev mode)
datafoundry deploy --config platform-configs/examples/fail-at-orchestration.yaml
```

**Expected**:
1. Run stops at the `orchestration` step with `status: failed` and a human-readable `error_detail`; earlier steps show `succeeded`; later steps remain `pending` (US1-AC3).
2. Partial state is inspectable: resources from succeeded steps exist; nothing destroyed automatically (edge case: failed midway).
3. `POST /runs/{run_id}/retry` resumes **from the failed step** (attempt increments; succeeded steps not re-executed destructively).
4. Alternatively `POST /runs/{run_id}/rollback` destroys only this run's resources (per-run workspace); afterwards zero orphaned resources remain (verify against LocalStack inventory) and platform status is `destroyed`. Rollback completes < 15 min (SC-005).

## Scenario 4: Reproducibility (US2, SC-002, FR-011)

```bash
# Export config of the platform deployed in Scenario 2
datafoundry export --platform customer-analytics-dev > exported.yaml

# Destroy, then redeploy from the export
datafoundry destroy --platform customer-analytics-dev --wait
datafoundry deploy --config exported.yaml --wait
```

**Expected**:
1. `exported.yaml` contains every parameter needed to recreate the platform and **no secrets** — verify with `gitleaks detect exported.yaml` (clean) and confirm credential fields are `secretRef` only (SC-006).
2. Redeployed platform matches the original: same capabilities, zones, settings (diff of `GET /platforms/{id}` before/after shows only timestamps/run ids changed).
3. `config_hash` of export equals hash of redeployed config version (determinism).

## Scenario 5: Production controls & name uniqueness (FR-010, FR-013, edge cases)

```bash
# Production without approval
datafoundry deploy --config platform-configs/examples/prod-no-approval.yaml
# Expected: rejected in validation — approval.ref required; nothing provisioned.

# Duplicate name in same cloud scope
datafoundry deploy --config platform-configs/examples/dev-aws-localstack.yaml  # second time
# Expected: 409 name_taken with clear error (second user's view); first platform untouched.
```

## Scenario 6: Cloud parity check (FR-002, SC-003) — sandbox accounts, manual gate

```bash
datafoundry deploy --config platform-configs/examples/dev-gcp-sandbox.yaml --wait
datafoundry deploy --config platform-configs/examples/dev-aws-sandbox.yaml --wait
```

**Expected**: run the capability-parity checklist (generated from `GET /capabilities`): both platforms expose the identical logical capability set, identical API shapes, identical zone layout; provider-native resource ids differ but no platform-behaviour difference is visible to consumers. Deployment completes < 30 min in 95% of runs (SC-001 — tracked across repeated sandbox runs).

## Scenario 7: Health dashboard data (US3, FR-007)

```bash
curl -s -H "Authorization: Bearer $DF_TOKEN" \
  http://localhost:8000/api/v1/platforms/{platform_id} | jq '.health, .status'
```

**Expected**: response includes cloud, region, environment, per-component health with `last_check_at`, storage utilisation, latest run, recent failures. Break a component (stop the catalog container in dev), re-trigger `POST /platforms/{id}/health-checks`: platform flips to `degraded`, the failed component is flagged with reason and last check time (US3-AC3).

---

## Test suite map

| Level | Command | Covers |
|---|---|---|
| Unit | `cd control-plane && uv run pytest tests/unit` | config validation rules, step ordering, secret scan, state machine transitions |
| Contract | `uv run pytest tests/contract` | API responses match `contracts/deployment-api.md`; Pydantic schema matches `platform-config-schema.md`; capability registry matches `capability-catalog.md` |
| Terraform | `terraform validate` + `tflint` per module in CI; `terraform plan -detailed-exitcode` on rendered workspaces | FR-006, module input/output contracts |
| Integration | `uv run pytest tests/integration` (docker compose + LocalStack) | Scenarios 1–5, 7 automated |
| E2E (manual gate) | Sandbox account runs, recorded in run history | Scenario 6, SC-001 timing |

## Cleanup

```bash
datafoundry destroy --platform <name> --wait   # per platform
docker compose -f docker/docker-compose.dev.yml down -v   # local deps
```
