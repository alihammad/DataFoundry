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

## Ingestion (feature 002)

Self-service data ingestion: register a source, configure tables/files, and
the platform auto-creates a pipeline that lands validated data in Bronze with
full batch metadata. Design artifacts in
`../specs/002-data-ingestion/` (contracts, data model, quickstart).

### Architecture

```text
src/datafoundry/controlplane/ingestion/
├── gateway.py        # SourceGateway/LandingGateway ABCs + SimulatedSourceGateway
├── connectors/       # Connector ABC + registry (postgres, sqlserver, object_storage)
├── engine.py         # extract -> validate -> land/quarantine batch pipeline
├── validation.py     # file validation, contract compat, record-count reconciliation
├── contract.py       # contract inference + change classification
├── scheduler.py      # in-process background ticker (R-04)
├── alerts.py         # structured, secret-redacted alerts to pipeline owner
└── security.py       # redact_ingestion + scan_ingestion_payload (SC-007)
```

The engine never talks to a source SDK directly — it goes through
`SourceGateway`. `SimulatedSourceGateway` provides in-memory fake
PostgreSQL/SQL Server/object-storage inventories with fault-injection hooks
(`force_auth_fail`, `force_network_unreachable`, `force_schema_change`,
`force_corrupt_file`) so every connector/validation/quarantine path is
exercisable offline — no docker/terraform/database required.

### Connector framework

A connector implements the `Connector` ABC (`discover_schema`,
`test_connection`, `extract`) and is registered in `connectors/registry.py`
mapping `source_type` → connector class. To add a new source type:

1. Add a connector module under `connectors/` implementing the ABC.
2. Register it in `connectors/registry.py`.
3. Add the `source_type` to the ingestion config schema if it needs new
   fields (`config/ingestion_schema.py`).

No changes to the engine or existing connectors are required (FR-015 spirit).

### Simulated-gateway testing

Tests drive the ingestion worker explicitly via the `process_ingestion_run`
fixture (the app's dispatcher is a no-op in tests). The scheduler is exercised
directly via `IngestionScheduler.tick()` — it is disabled in tests
(`ingestion_scheduler_enabled=False`) and starts in the app lifespan in
production.

### API surface

- `POST /sources`, `POST /sources/{id}/test`, `GET /sources[/{id}]`
- `POST /sources/{id}/config`, `GET /sources/{id}/config`
- `GET /pipelines`, `POST /pipelines/{id}/run|pause|resume`
- `GET /pipelines/{id}/runs`, `GET /runs/{id}`, `GET /batches/{id}`,
  `GET /runs/{id}/logs`, `POST /runs/{id}/retry`
- `GET /sources/{id}/contracts`, `POST /contracts/{id}/approve`
- `GET /quarantine`

Note: `GET /runs/{id}` and `POST /runs/{id}/retry` are shared with the
deployment API (feature 001). The ingestion router is registered first and
dispatches by run type.

## Semantic layer (feature 006)

Define business metrics once over Gold/Silver datasets and consume them
everywhere with the same value, governed through a GitOps lifecycle. Design
artifacts in `../specs/006-semantic-layer/` (contracts, data model, quickstart).

### Architecture

```text
src/datafoundry/controlplane/semantic/
├── model/          # compose_semantic_model: validate config -> resolve datasets -> build model
├── compute/        # compile_metric_query + compute_metric over DuckDB via the gateway
│   └── gateway.py  # SemanticGateway ABC + SimulatedSemanticGateway (in-memory fixtures)
├── tests/          # SemanticTest ABC, registry, and the four categories
├── lifecycle.py    # propose -> validate -> approve -> publish (GitOps, FR-003/004/005)
├── access.py       # role-based visibility + column/row protection (reuses feature 005)
├── discovery.py    # search business terms; certified vs draft (FR-011)
├── consumers.py    # consumer registration + breaking-change notification (FR-005/010)
└── deprecation.py  # metric deprecation with successor + availability period (FR-010)
```

The semantic engine never talks to a cloud SDK directly — it goes through
`SemanticGateway`. `SimulatedSemanticGateway` provides in-memory fake
Gold/Silver tables (orders, customers) with protected columns, row-level
restrictions, staleness, and quality-state flags plus fault-injection hooks
(`force_stale_data`, `force_quality_failure`, `force_fanout`) so every
metric-definition, semantic-test, publication, access, and discovery path is
exercisable offline.

### API surface

- `POST /semantic/models`, `GET /semantic/models[/{id}]`
- `POST /semantic/models/{id}/metrics`, `GET /semantic/metrics/{id}`,
  `POST /semantic/metrics/{id}/query`
- `POST /semantic/models/{id}/tests`, `POST /semantic/tests/{id}/run`
- `POST /semantic/models/{id}/publish`, `POST /publications/{id}/approve`,
  `GET /semantic/models/{id}/publications`
- `GET /semantic/discovery?q=...`
- `POST /semantic/metrics/{id}/consumers`, `GET /semantic/metrics/{id}/consumers`
- `POST /semantic/metrics/{id}/deprecate`

### Governance

A metric change flows through propose → validate → approve → publish. Semantic
tests (calculation, reconciliation, relationship, filter) run at publish time;
a failing test blocks publication with failure detail (FR-004). Breaking
changes require explicit approval and notify registered consumers (FR-005).
Deprecated metrics remain available for a bounded period with a successor
reference (FR-010).
