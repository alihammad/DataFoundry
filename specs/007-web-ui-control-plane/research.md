# Phase 0 Research: Web UI Control Plane

**Feature**: 007-web-ui-control-plane | **Date**: 2026-09-16

All Technical Context unknowns resolved. Format: Decision / Rationale / Alternatives considered.

---

## R-01: Frontend technology — React + Vite SPA served by the control plane

**Decision**: Build the UI as a **single-page application (SPA)** with **React 18 + TypeScript**, bundled with **Vite 5**, and served as static assets by the existing FastAPI control plane (a new `ui/` package in the monorepo). Routing via React Router; server-state via TanStack Query.

**Rationale**:
- The spec (Assumptions) explicitly defers frontend technology to planning. React + Vite is the most widely supported, well-documented SPA stack, giving the fastest path to the required views (dashboard, wizards, lists, drill-downs) with a large component ecosystem.
- Serving the built SPA from the control plane keeps a single deployment artifact (FR-001, Principle II): one container serves both the API and the UI, no separate static host or CDN to provision. This matches the existing ECS Fargate / Cloud Run deployment model.
- TypeScript gives typed access to the control-plane API (the OpenAPI schema is the source of truth), reducing the class of bugs the spec's edge cases target (concurrent edits, honest degradation, protection-aware previews).
- TanStack Query provides the caching/refetch/polling primitives the dashboard needs (60-second refresh window, SC-003) and the optimistic-concurrency handling for wizard saves (FR-017).
- Vite's dev server proxies to the control plane in development, so the UI and API share an origin in production (no CORS) and a proxied origin in dev.

**Alternatives considered**:
- *Next.js (SSR)*: server-side rendering adds a Node runtime and a second deployment artifact, complicating the single-artifact model; the UI is an authenticated internal tool where client-side rendering is sufficient. Rejected for MVP.
- *Vue + Vite*: equally viable; React chosen for ecosystem breadth and the team's familiarity. Not a correctness difference.
- *Svelte*: lighter, but smaller ecosystem for the component/data-grid needs (lineage graph, SQL editor, dashboards). Rejected for MVP.
- *Separate static host (S3/CloudFront, GCS/CDN)*: adds infrastructure and a second origin, complicating auth (bearer token propagation) and violating the single-artifact simplicity. Rejected.

## R-02: Component library — lightweight, headless-first

**Decision**: Use a **headless-first component library** (e.g. Radix UI primitives) with a small set of presentational components built in-house, plus a data-grid library (e.g. TanStack Table) for the paginated/virtualised lists (FR-019). No heavy opinionated design system.

**Rationale**:
- The UI has many bespoke views (dashboard tiles, wizards, lineage graph, SQL editor, quarantine filters). A headless library gives accessible primitives (dialog, select, tabs, table) without imposing a visual theme, letting the in-house components match the platform's needs.
- TanStack Table handles the pagination/virtualisation requirement (FR-019) and the filterable lists (quarantine, audit log, quality history) without a heavyweight grid.
- Keeps the bundle small and the styling approach simple (CSS modules / plain CSS), consistent with the "simplicity, not popularity" governance principle.

**Alternatives considered**:
- *Material UI / Ant Design*: full design systems with strong defaults but heavy theming and a large opinionated surface; overkill for an internal tool and harder to keep cloud-neutral/consistent. Rejected for MVP.
- *Tailwind + custom everything*: flexible but more upfront work for accessible primitives (dialogs, selects, tables). Rejected; headless primitives give accessibility for free.

## R-03: Auth in the UI — bearer token + provider header, no session endpoints

**Decision**: The UI authenticates per-request using the existing control-plane auth model (feature 001 `api/auth.py`): in `cloud_iam` mode it sends `Authorization: Bearer <token>` + `x-datafoundry-provider: aws|gcp` on every API call; in `dev` mode no headers are needed. The UI does NOT add login/session endpoints — the token is obtained out-of-band from the organisation's identity provider (spec Assumptions: "Authentication uses the organisation's identity provider").

**Rationale**:
- The control plane has no session/login API and the spec explicitly says the UI does not manage passwords. Reusing the per-request bearer model keeps one auth path across CLI and UI.
- The UI stores the token in memory (or sessionStorage) and attaches it via the typed API client; on 401/403 it surfaces the permission explanation from the problem+json `missing[]` array (FR-013).
- Wizard state preservation across session expiry (FR-021) is handled client-side (draft persisted to localStorage keyed by wizard + user), not by a server session.

**Alternatives considered**:
- *Server-side sessions / cookies*: would require new backend auth infrastructure and a session store, duplicating the IdP's job. Rejected.
- *OAuth2 PKCE in the UI*: the spec defers IdP integration to feature 001's assumption; adding a full OAuth flow is out of MVP scope. The bearer-token model is the documented contract.

## R-04: UI-owned backend capabilities — minimal, governed

**Decision**: The UI adds a small set of **UI-owned backend capabilities** to the control plane: static SPA serving, saved queries, notification channel configuration, UI roles (RBAC), pending-approval aggregation, and audit-log search. These are new routers + models in the existing control plane, reusing its DB, audit, secret-scan, and settings abstractions. All other data is read through the existing features 001–006 APIs.

**Rationale**:
- The spec's Key Entities include Saved Query, Notification Channel Configuration, UI Role, Pending Approval, and Audit Trail Entry — these are UI-owned and need persistence. The rest of the UI is a thin client over existing APIs.
- Reusing the control-plane DB/audit/secret-scan keeps one governance model (FR-015, FR-022): saved queries are secret-scanned, roles/approvals are audited, notification config never stores credentials in plaintext.
- Pending-approval aggregation (FR-016) is a read-side view over the existing approval records (contracts, overrides, semantic publications, production changes) — a UI router that queries the existing tables, not new business logic.

**Alternatives considered**:
- *UI-only (no backend additions)*: saved queries, notification channels, and roles would have nowhere to persist; the spec's Key Entities require them. Rejected.
- *Separate UI backend service*: adds a second service and deployment artifact, violating the single-artifact model (R-01). Rejected.

## R-05: Static serving + SPA fallback

**Decision**: The control plane mounts the built SPA as static files and serves a catch-all fallback to `index.html` for non-API routes (so client-side routing works on refresh). The `/api/v1` prefix is reserved for the API; the UI is served at `/` (or a configurable `DF_UI_BASE_PATH`). A `DF_UI_STATIC_DIR` setting points at the built assets.

**Rationale**:
- FastAPI's `StaticFiles` + a catch-all route is the standard SPA-serving pattern; it keeps one origin (R-01) and one artifact.
- The catch-all must exclude `/api/*` and `/healthz` so API routes are never swallowed by the SPA fallback.
- The static-dir path is a `DF_UI_*` env var (dev-only/ops knob), consistent with the settings pattern (feature 001) — never in platform config YAML.

**Alternatives considered**:
- *Separate nginx serving the SPA*: adds a second container and origin; rejected for the single-artifact model.
- *No fallback (hash routing)*: avoids the fallback route but gives uglier URLs and weaker deep-linking; rejected.

## R-06: Dashboard data aggregation

**Decision**: The dashboard (US1) is composed from the existing API endpoints: platform list/detail (health, storage utilisation, latest run, recent failures), runs history (pipeline counts), quality endpoints (overall quality score), health checks, and capabilities. The UI aggregates these client-side with TanStack Query polling on a 60-second interval (SC-003). Each tile links to its underlying detail view (FR-003).

**Rationale**:
- The implemented API already exposes every dashboard figure (platform detail, runs, quality, health). No new aggregation endpoint is needed for MVP; client-side composition keeps the backend thin.
- TanStack Query's polling + stale-while-revalidate gives the 60-second refresh window and honest degradation (FR-018): a failed fetch leaves the last-known value with a "stale" timestamp, never a misleading zero.
- Multi-platform context (FR-020) is a client-side selected-platform state that scopes all queries.

**Alternatives considered**:
- *Server-side dashboard aggregation endpoint*: would centralise the composition but adds a new endpoint and couples the backend to UI presentation. Rejected for MVP; revisit if polling load grows.

## R-07: SQL editor + saved queries

**Decision**: The SQL editor (US4, FR-010) runs queries through the existing semantic/query API (feature 006) and the catalog/query surface (feature 003), subject to the querying user's access and protection policies. Saved queries are persisted via a new UI-owned `SavedQuery` model + router; execution always re-evaluates the runner's access rights (spec Key Entity). Download applies the same protection policies as the query.

**Rationale**:
- The spec's Key Entity "Saved Query" requires persistence; the execution path is the existing query API (the UI never bypasses access/protection — FR-010, SC-006).
- Saved queries are secret-scanned on write (FR-022) and audited (FR-015); sharing is by reference, and the recipient's own access rights are re-evaluated on open (US4-AC4).

**Alternatives considered**:
- *Client-side-only saved queries (localStorage)*: not shareable across users and not auditable; violates the Key Entity and FR-015. Rejected.

## R-08: Administration — roles, approvals, notifications, audit log

**Decision**: Administration (US6) is a set of UI-owned routers + models: `UIRole` (RBAC at platform/dataset/column scope, FR-013/FR-014), `NotificationChannel` (per-platform alert routing, FR-014), pending-approval aggregation (FR-016), and audit-log search (FR-014). All admin actions are audited (FR-015). Roles are enforced on the frontend (hide/disable) AND re-checked by the backend on every action (the UI never trusts the client).

**Rationale**:
- The spec's Key Entities (UI Role, Notification Channel Configuration, Pending Approval, Audit Trail Entry) require persistence and search.
- Backend re-enforcement is mandatory: the UI hides/disabled denied areas (FR-013) but the backend remains the authority (the UI is a client, not a security boundary).
- Audit-log search reuses the existing audit service (feature 001) with a search router over time/identity/resource/action (FR-014).

**Alternatives considered**:
- *Frontend-only RBAC*: hides controls but is trivially bypassed; violates FR-013's "users see and can do only what their roles permit". Rejected — backend enforcement is required.

## R-09: Concurrency, degradation, and wizard-state edge cases

**Decision**: Concurrent-edit safety (FR-017) uses optimistic concurrency: the UI sends the config version/hash it edited against; the backend rejects a conflicting save with a 409 showing the current version (the existing `config_hash`/`config_version` fields on platforms/gates/contracts provide the version token). Honest degradation (FR-018) is handled by TanStack Query's stale-state rendering. Wizard state (FR-021) is persisted to localStorage keyed by wizard + user, resumed after re-auth.

**Rationale**:
- The existing API already returns `config_hash`/`config_version` on config exports; the UI echoes it back on update, and the backend's existing conflict handling (409 `name_taken`/`active_run`) is extended to version conflicts.
- These are client-side concerns; no new backend logic beyond the version-conflict check.

**Alternatives considered**:
- *Last-write-wins*: violates FR-017 (no silent overwrites). Rejected.
- *Server-side draft store*: adds persistence for transient wizard state; localStorage is sufficient and simpler. Rejected.