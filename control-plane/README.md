# DataFoundry Control Plane

FastAPI service that deploys governed lakehouse platforms on AWS/GCP in one
click. Part of the DataFoundry monorepo — see `../specs/001-one-click-platform-deployment/`
for design artifacts and `../README.md` for the architecture overview.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

## Layout

```text
src/datafoundry/controlplane/
├── api/            # FastAPI routers (platforms, runs, validate, capabilities, health)
├── config/         # PlatformConfig schema, validation, secret scan, export, versioning
├── capabilities/   # code-defined capability registry (dependency graph, deploy order)
├── providers/      # AWS/GCP adapters (regions, matrix, state backend, credential probe)
├── engine/         # worker, orchestrator, terraform wrapper, generator, gateway, init jobs
├── health/         # health-check runners, readiness rule, storage utilisation
├── audit/          # append-only audit records (secret-scanned)
├── db/             # SQLAlchemy models, state machines, session, migrations
└── observability.py # OTel wiring + secret-redacting JSON logging
```

## Configuration

All runtime settings come from `DF_*` environment variables
(`config/settings.py`). Dev-only knobs (LocalStack endpoint, fault injection,
auth bypass, simulated cloud) live here — **never** in the platform config
YAML, which stays cloud-neutral and strict.

Key settings:

| Var | Purpose |
|---|---|
| `DF_DATABASE_URL` | Metadata-store DSN (default local Postgres) |
| `DF_TERRAFORM_ROOT` | Path to the `terraform/` module tree |
| `DF_SIMULATE_CLOUD` | `1` = in-memory gateway (tests/dev), `0` = real Terraform |
| `DF_AWS_ENDPOINT_URL` | LocalStack endpoint (dev-only) |
| `DF_FAULT_INJECTION` / `DF_FAULT_INJECTION_STEP` | Force a step failure (quickstart Scenario 3) |
| `DF_AUTH_MODE` | `dev` (static identity) or `cloud_iam` (federated) |
| `DF_OTEL_ENABLED` | OpenTelemetry tracing |

## Tests

```bash
.venv/bin/pytest tests/unit tests/contract -v    # 160 tests
```

Tests use in-memory SQLite (fresh `StaticPool` engine per test — no
`drop_all`, circular FKs). The worker runs against `SimulatedCloudGateway`;
tests override `app.state.dispatcher` with a no-op and drive `WorkerRunner`
explicitly (see `tests/conftest.py`).

## Migrations

```bash
.venv/bin/alembic upgrade head          # apply
.venv/bin/alembic upgrade head --sql    # offline SQL (no local Postgres needed)
```

## Contract conformance

The API, config schema, and capability catalog are contract-tested against
`specs/001-one-click-platform-deployment/contracts/`. Any change to an error
shape, route, or capability key must update the matching contract and test.
