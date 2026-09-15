# Quickstart: Web UI Control Plane

**Feature**: 007-web-ui-control-plane | **Date**: 2026-09-16

Runnable validation scenarios proving the web UI works end to end. See [ui-api.md](./contracts/ui-api.md), [ui-contract.md](./contracts/ui-contract.md), and [data-model.md](./data-model.md) for details.

## Setup (local development)

- Feature 001 control plane running (see `specs/001-one-click-platform-deployment/quickstart.md`) — the API, a deployed platform, and the `datafoundry` CLI in the venv.
- Features 002–006 capabilities available (data sources, pipelines, quality gates, security classification, semantic models) for the configuration wizards.
- Control plane in `dev` auth mode (`DF_AUTH_MODE=dev`) so the UI needs no bearer token.

```bash
cd ui && npm install && npm run dev   # Vite dev server, proxies /api to control plane
# or build + serve from the control plane:
cd control-plane && source .venv/bin/activate && uvicorn datafoundry.controlplane.api.app:app
```

---

## Scenario 1: Platform dashboard (US1, FR-002, FR-003)

Deploy a platform with known state (some healthy pipelines, one failure), then open the dashboard.

**Expected**:
1. All summary figures (pipelines, quality, storage, cost, failures, deployments) reflect actual state within the 60-second refresh window (SC-003).
2. Clicking the failures tile reaches the failure list; drilling into a specific run shows its logs and gate report within two navigation steps (FR-003, SC-005).
3. With multiple platforms, switching platform context re-renders the whole UI for the selected platform (FR-020).

---

## Scenario 2: Configure everything through the UI (US2, FR-004, FR-005)

Complete an end-to-end journey purely in the UI: create a platform, add a data source, configure a quality gate, classify data.

**Expected**:
1. The data source wizard creates, validates, version-controls, and makes deployable the ingestion config without manual file editing (US2-AC1).
2. A change requiring approval (e.g. Production) enters the approval workflow, shows pending state, and takes effect only after approval (US2-AC2).
3. A user without permission for a config area sees edit actions hidden/disabled with explanation (US2-AC3, FR-013).
4. Every UI-made change is indistinguishable in governance terms from a code-made change — same validation, same audit trail (US2-AC4, SC-004).

---

## Scenario 3: Pipeline and run management (US3, FR-006, FR-007)

Exercise each pipeline action in the UI against a live pipeline.

**Expected**:
1. Triggering a manual run starts it, shows live status, and lands in execution history (US3-AC1).
2. Retrying a failed run runs without duplicating ingested data; history links retry to original (US3-AC2).
3. Filtering quarantine by failure reason and replaying fixed entries executes replay and updates entry states (US3-AC3).

---

## Scenario 4: Catalog browsing and dataset exploration (US4, FR-008, FR-009, FR-010)

Search a seeded catalog, open a dataset, run and save a query, download results.

**Expected**:
1. Searching a business term returns matching datasets and metrics ranked with owner, quality, and freshness visible (US4-AC1).
2. Opening a dataset with lineage renders upstream sources and downstream consumers as a navigable graph (US4-AC2).
3. Previewing/querying a dataset with protected columns shows masked/tokenised values per the user's rights (US4-AC3, SC-006).
4. Sharing a saved query lets a colleague open and run it subject to their own access rights (US4-AC4).

---

## Scenario 5: Quality and monitoring views (US5, FR-011, FR-012)

Generate known quality events (failed gate, contract violation, stale data) and verify each appears in the correct view.

**Expected**:
1. A gate failure's failing run, test, and failed-record drill-down are reachable within two navigation steps (US5-AC1, SC-005).
2. Filtering alert history by time range and severity shows matching alerts with delivery status (US5-AC2).
3. Cost-by-pipeline figures reconcile with the platform's cost observability source (US5-AC3).

---

## Scenario 6: Administration and access management (US6, FR-013, FR-014, FR-015, FR-016)

Create a role with scoped permissions, assign a user, and search the audit log.

**Expected**:
1. A role scoped to specific datasets with column restrictions gives users exactly the scoped capabilities across the UI (US6-AC1).
2. A gate-override request reaches configured approvers in the UI, who approve/deny with recorded reasoning (US6-AC2, FR-016).
3. Searching the audit log shows every administration action with actor, timestamp, and before/after state (US6-AC3, FR-015).

---

## Edge-case validation

- **Concurrent edit** (FR-017): two users edit the same config; the second save is rejected with a conflict showing the current version — no silent overwrite.
- **Backing service down** (FR-018): a dashboard tile shows stale/unavailable state with last-known timestamp, never a misleading zero.
- **Session expiry mid-wizard** (FR-021): draft state is preserved; after re-auth the user resumes where they left off.
- **Deleted drill-down target** (FR-018): navigation reports "resource no longer exists" and returns to a valid view.
- **Protected data in preview** (SC-006): previews enforce the same protection policies as queries; no privileged UI path to raw protected values.