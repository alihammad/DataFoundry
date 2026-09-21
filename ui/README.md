# DataFoundry Web UI

The web UI control plane (feature 007): a browser-based interface through which all platform configuration is set and the entire platform is monitored. It is the primary control plane for users who do not interact with infrastructure code or cloud consoles.

## Stack

- **React 18 + TypeScript** SPA, bundled with **Vite 5**
- **React Router** (routing), **TanStack Query** (server-state/data fetching)
- **Radix UI** primitives + **TanStack Table** (headless-first, R-02)
- **Vitest** (unit) + **Playwright** (E2E)

## Development

```bash
cd ui
npm install
npm run dev        # Vite dev server on :5173, proxies /api to the control plane
```

The dev server proxies `/api` to `http://localhost:8000` (override with `DF_API_URL`). In `dev` auth mode (`DF_AUTH_MODE=dev`) no bearer token is needed; in `cloud_iam` mode the UI sends `Authorization: Bearer <token>` + `x-datafoundry-provider` on every call.

## Build

```bash
npm run build      # outputs ui/dist
```

The built SPA is served by the control plane (single artifact, R-01). Set `DF_UI_STATIC_DIR` to the built `ui/dist` and `DF_UI_BASE_PATH` to the mount path (default `/`).

## Tests

```bash
npm test           # Vitest unit tests
npm run e2e        # Playwright E2E (requires a running control plane in dev mode)
```

## Views

- **Dashboard** (US1): platform health, pipeline counts, quality score, storage/compute utilisation, cost, recent failures/deployments; each tile drills into detail.
- **Configure** (US2): platform creation, data source, quality gate, and protection wizards — every change flows through the GitOps approval workflow.
- **Pipelines** (US3): pipeline/run management, retry/rollback, quarantine browsing + replay.
- **Catalog** (US4): catalog search, dataset detail, SQL editor with save/share/download.
- **Quality** (US5): per-dataset scores/trends, gate run history, observability.
- **Admin** (US6): roles, approvals, notification channels, audit log search.

## Security

- Never displays secrets, key material, credentials, or unprotected sensitive values (FR-022, SC-006).
- Previews enforce the same protection policies as queries.
- UI-made changes flow through the same version-controlled, approval-based workflow as code-made changes (FR-005, SC-004).