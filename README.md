# DataFoundry

One-click governed lakehouse platform deployment on AWS and GCP.

DataFoundry deploys a complete Medallion-architecture lakehouse — networking,
object storage with Bronze/Silver/Gold zones, identity, compute, orchestration,
metadata catalog, ingestion, data-quality gates, semantic layer, and
monitoring — from a single declarative configuration, with no manual
cloud-console work.

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                     Control Plane (FastAPI)                     │
│  validate → plan → provision (Terraform) → init → health-check  │
└───────────────┬─────────────────────────────────┬───────────────┘
                │  per-run workspaces             │  capability modules
                ▼                                 ▼
        terraform/workspaces/<run_id>/    terraform/{aws,gcp}/<capability>/
                                          terraform/control-plane/{aws,gcp}/
```

- **Control plane** (`control-plane/`) — FastAPI service. Validates a
  `PlatformConfig`, renders a per-run Terraform root module, drives the
  deployment worker, runs health checks, records audit history, and exposes
  the platform/run/capability API.
- **CLI** (`cli/`) — `datafoundry` typer client: `validate`, `deploy`,
  `status`, `export`, `destroy`.
- **Terraform** (`terraform/`) — cloud-specific capability modules
  (`aws/`, `gcp/`) implementing a common input/output contract, plus the
  control-plane bootstrap modules (`control-plane/`). Shared cloud-neutral
  glue in `modules/`.
- **Platform configs** (`platform-configs/`) — version-controlled GitOps
  source of truth for deployed platforms.

The platform is cloud-agnostic at the abstraction level: every logical
capability maps to cloud-specific implementations, but the configuration
format, API contracts, and logical behaviour are identical across AWS and GCP
(constitution Principle I, FR-002, SC-003).

## Quickstart

See [`specs/001-one-click-platform-deployment/quickstart.md`](specs/001-one-click-platform-deployment/quickstart.md)
for the runnable validation scenarios (1–7).

```bash
# Control plane
cd control-plane && pip install -e ".[dev]" && uvicorn datafoundry.controlplane.api.app:app --port 8000

# CLI
cd cli && pip install -e .
datafoundry validate --config ../platform-configs/examples/dev-aws-localstack.yaml
datafoundry deploy --config ../platform-configs/examples/dev-aws-localstack.yaml --wait
```

## Monorepo layout

| Path | Purpose |
|---|---|
| `control-plane/` | FastAPI control plane (Python 3.12) |
| `cli/` | `datafoundry` CLI |
| `terraform/` | Capability modules (`aws/`, `gcp/`), control-plane bootstrap, shared glue (`modules/`) |
| `platform-configs/` | GitOps platform configurations + examples |
| `docs/` | BRD, decision log, runbooks |
| `specs/` | Feature specs (spec-kit), contracts, quickstart |
| `scripts/` | Demo + parity-checklist generator |
| `docker/` | Dev dependencies + service images |

## Design artifacts

- `specs/001-one-click-platform-deployment/spec.md` — feature spec
- `specs/001-one-click-platform-deployment/contracts/` — API, config schema, capability catalog
- `docs/runbooks/` — bootstrap, disaster recovery, performance baseline
- `.specify/memory/constitution.md` — project constitution

## Development

See `control-plane/README.md` and `cli/README.md` for per-component developer
guides. CI runs ruff lint/format, gitleaks, unit/contract tests, and Terraform
`validate`/`tflint` across every module.
