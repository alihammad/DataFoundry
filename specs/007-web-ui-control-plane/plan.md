# Implementation Plan: Web UI Control Plane

**Branch**: `feature/007-web-ui-control-plane` | **Date**: 2026-09-16 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/007-web-ui-control-plane/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Deliver the platform's **web UI control plane**: a modern browser-based interface through which all platform configuration is set and the entire platform is monitored (FR-001). The UI is the primary control plane for users who do not interact with infrastructure code or cloud consoles. It exposes and governs the capabilities defined in features 001–006 — it adds no new business behaviour (spec Assumptions).

The UI provides: a **platform dashboard** (US1, P1) with single-pane health, pipeline counts, quality score, storage/compute utilisation, cost, recent failures and deployments, each tile drilling into detail within two navigation steps (FR-003); **configuration wizards** (US2, P1) for platform creation, data sources, quality gates, classifications/protection, and semantic approval workflows — every UI-made change flows through the same version-controlled, approval-based GitOps workflow as code-made changes (FR-005, SC-004); **pipeline and run management** (US3, P2) with trigger/pause/resume/retry and quarantine browsing/replay; **catalog browsing and dataset exploration** (US4, P2) with search, lineage, protection-aware previews, and a SQL editor with save/share/download (FR-010); **quality and monitoring views** (US5, P3); and **administration** (US6, P3) with RBAC, approval workflows, notification channels, and audit log search (FR-014).

The UI is **cloud-independent** (FR-023, SC-007): identical screens and workflows regardless of the platform's underlying cloud. It enforces role-based access on every view and action (FR-013), degrades honestly when a backing service is down (FR-018), handles concurrent edits safely (FR-017), preserves wizard state across session expiry (FR-021), and never displays secrets or unprotected sensitive values (FR-022, SC-006).

This feature is the first frontend in the monorepo. It consumes the existing control-plane REST API (features 001–006) and adds a small set of UI-owned backend capabilities (static serving, saved queries, notification channels, UI roles, pending-approval aggregation, audit-log search). Frontend technology is a planning-time decision (spec Assumptions) — see R-01.

## Technical Context

**Language/Version**: TypeScript 5.x (frontend) + Python 3.12 (control plane backend additions). The UI is a new frontend package in the monorepo; the backend additions are modules inside the existing control plane.

**Primary Dependencies**: Frontend — React 18 + Vite 5 (build tooling), TypeScript, React Router (routing), TanStack Query (server-state/data fetching), a lightweight component library (see R-02). Backend — FastAPI (static serving + new UI routers), SQLAlchemy 2 + Alembic (UI-owned persistence: saved queries, notification channels, UI roles), existing OpenTelemetry + structured-logging + audit + secret-scan reused unchanged. Testing — Vitest + React Testing Library (unit), Playwright (E2E), pytest (backend contract/integration).

**Storage**:
- UI-owned metadata (saved queries, notification channel config, UI roles, pending-approval aggregation views): the same PostgreSQL 15 provisioned by feature 001 (reuses `db/` models + Alembic; new migration).
- All business data (platforms, runs, datasets, gates, contracts, quarantine, quality, semantic, security) lives in the existing control-plane DB and is read through the existing API — the UI stores no business data of its own (spec Assumptions).

**Testing**: Frontend — Vitest unit tests for components/hooks, Playwright E2E for the quickstart scenarios against a running control plane in `dev` auth mode. Backend — pytest contract tests for the new UI routers + integration tests for the UI-owned flows. The existing in-memory SQLite harness (feature 001 conftest pattern) is reused for backend tests. Live E2E against sandbox data gated manually.

**Target Platform**: Browser (modern evergreen), served as a static SPA from the control plane; containerised with the same deployment artifact as features 001–006 (ECS Fargate / Cloud Run). Responsive layout (FR-019).

**Project Type**: Web application (frontend SPA + backend static-serving/API extension). Single monorepo.

**Performance Goals**: Dashboard figures reflect backing state within a 60-second refresh window (SC-003); lists paginate or virtualise (FR-019); the full self-service journey completes in under 45 minutes (SC-001).

**Constraints**: UI-made changes MUST flow through GitOps, never bypass it (FR-005, SC-004); role-based access enforced on every view/action (FR-013); honest degradation on partial outages (FR-018); concurrent-edit safety (FR-017); wizard state preserved across session expiry (FR-021); never display secrets/protected values (FR-022, SC-006); cloud-independent behaviour (FR-023, SC-007); responsive + paginated (FR-019).

**Scale/Scope**: MVP — dashboard, configuration wizards, pipeline/run management, catalog browsing + SQL editor, quality/monitoring views, administration basics. Deferred per spec Assumptions: APIs management, Agents management, full semantic-layer authoring UI, notebooks, internationalisation, theming, offline support. Tens of platforms, hundreds of datasets.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Requirement | Plan Compliance | Status |
|---|---|---|---|
| I. Cloud Independence via Portable Core | Logical config portable; new provider without touching core | UI is cloud-independent (FR-023, SC-007): identical screens/workflows regardless of cloud; consumes the cloud-neutral REST API; no cloud-specific code in the frontend | ✅ PASS |
| II. Infrastructure as Code (Terraform) | All infra reproducible from code | No new infra — the UI is a static SPA served by the existing control plane; UI-owned metadata uses the existing control-plane DB; deployable as a feature-001 capability | ✅ PASS |
| III. Medallion Architecture with Quality-Gated Promotion | Consume only quality-gated data; never silently serve stale/failed data | UI surfaces quality scores, gate reports, quarantine, and freshness from features 003/004; dashboard tiles degrade honestly on stale/unavailable data (FR-018, SC-003) | ✅ PASS |
| IV. Shift-Left Testing & Data Contracts | Tests before/during; contracts validated; breaking blocks | UI configuration wizards surface inline validation errors from the backend (422 `errors[]`); UI-made changes flow through the same validation + approval workflow as code (FR-005); Playwright E2E + contract tests gate the UI | ✅ PASS |
| V. AI Agents with Human Oversight | No unrestricted AI production access; deterministic validation before execution | No AI components in this feature; the UI is a deterministic client of the governed API; AI/ML consumers get feature datasets under the same access policies (FR-013) | ✅ PASS |
| Security & Data Protection | Encryption at rest/in transit; secrets never plaintext; KMS; auditability | UI never displays secrets/key material/credentials (FR-022, SC-006); previews enforce the same protection policies as queries (spec Edge Cases); all admin/config actions audited (FR-015); auth via federated IdP bearer token (feature 001) | ✅ PASS |
| Development Workflow & Quality Gates | GitOps; observability by default; self-service reuse | UI-made changes flow through GitOps (FR-005, SC-004); UI actions audited with actor/timestamp/before-after (FR-015); UI built once, all users consume; observability via OpenTelemetry | ✅ PASS |
| Governance | Tech decisions driven by portability/simplicity/cost, not popularity | Frontend stack evaluation recorded in research.md (R-01/R-02) with explicit rationale; component library chosen on simplicity/maintainability, not popularity | ✅ PASS |

**Gate result**: PASS — no violations, Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/007-web-ui-control-plane/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── ui-api.md        #   UI-owned backend REST API
│   └── ui-contract.md   #   UI component/view contract
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
ui/                          # NEW frontend package (Vite + React + TS)
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx
│   ├── app/                 #   app shell, routing, auth context
│   │   ├── App.tsx
│   │   ├── router.tsx
│   │   ├── auth.tsx         #   bearer-token + provider-header handling
│   │   └── api.ts           #   typed API client (problem+json parsing)
│   ├── components/          #   shared UI components
│   ├── features/            #   per-view feature modules
│   │   ├── dashboard/       #   US1
│   │   ├── config/          #   US2 wizards
│   │   ├── pipelines/       #   US3
│   │   ├── catalog/         #   US4
│   │   ├── quality/         #   US5
│   │   └── admin/           #   US6
│   └── styles/
└── tests/                   #   Vitest unit + Playwright E2E

control-plane/src/datafoundry/controlplane/
├── api/                     # NEW routers: ui (static serving), saved-queries,
│   │                        #   notifications, roles, approvals, audit-log
│   ├── ui.py                #   static SPA serving + fallback
│   ├── saved_queries.py
│   ├── notifications.py
│   ├── roles.py
│   ├── approvals.py
│   └── audit_log.py
├── db/
│   ├── models.py            #   + SavedQuery, NotificationChannel, UIRole,
│   │                        #     PendingApprovalView
│   └── migrations/          #   + new Alembic migration
├── audit/service.py         #   + UI-originated audit actions (reused)
├── config/settings.py       #   + DF_UI_* knobs (static dir, CORS origins)
└── config/                  #   + UI-owned schema (saved query, notification,
    └── ui_schema.py         #     role) — strict Pydantic

control-plane/tests/
├── contract/                # ui-api contract tests
└── integration/             # UI-owned flow tests

docker/
├── Dockerfile.ui            #   NEW: build + serve the SPA
└── docker-compose.dev.yml   #   + ui service (dev)
```

**Structure Decision**: Single monorepo with a new `ui/` frontend package, mirroring the existing `control-plane/` and `cli/` layout. The UI is a static SPA built with Vite and served by the control plane (R-01). UI-owned backend capabilities (saved queries, notification channels, UI roles, pending-approval aggregation, audit-log search, static serving) are new routers/models in the existing control plane, reusing its DB, audit, secret-scan, and settings abstractions. New CLI commands are NOT required for this feature (the UI is the interface; the CLI already covers features 001–006).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

No violations — Complexity Tracking not required.
