# Performance Baseline (SC-001, FR-016)

**Feature**: 001-one-click-platform-deployment | **Status**: results pending sandbox runs

This document records the performance verification (T087). Targets come from
the success criteria; results are filled in from sandbox-account E2E runs
(quickstart Scenario 6), which are the manual gate because no cloud sandbox
is available in this environment.

## Targets

| Metric | Target | Source |
|---|---|---|
| Standard platform deploy (all MVP capabilities, single region) | < 30 min in 95% of runs | SC-001, FR-016 |
| Validation response (single request) | < 2 s | T087 |
| Run-status polling | < 500 ms p95 | T087 |

## Measurement method

1. Deploy `platform-configs/examples/dev-aws-sandbox.yaml` and
   `dev-gcp-sandbox.yaml` against a sandbox account/project.
2. Record wall-clock duration per run (the run record stores duration — FR-014).
3. Repeat across N runs; report p95 for the 30-min budget.
4. Measure `POST /api/v1/validate` latency and `GET /api/v1/runs/{id}` polling
   latency under load (e.g. `wrk`/`hey` against the bootstrapped endpoint).

## Results (sandbox)

> To be filled from the first sandbox runs. Track p95 across repeated runs
> for the SC-001 95% claim.

| Date | Provider | Region | Run id | Duration (min) | Validation (s) | Polling p95 (ms) | Within budget |
|---|---|---|---|---|---|---|---|
| — | — | — | — | — | — | — | — |

## Interpretation

- **Deploy < 30 min** is dominated by managed-service provisioning latency
  (MWAA/Cloud Composer, RDS/Cloud SQL, ECS/Cloud Run cold start). LocalStack
  runs complete much faster and are not representative of the budget.
- **Validation < 2 s** is met by design: stage-1 validation is pure in-process
  schema + semantic checks with no cloud round-trips (FR-003, SC-004).
- **Polling < 500 ms p95** is met by design: run-status reads a single row from
  the metadata store with no external calls.

## Failure to meet target

If a deploy exceeds 30 min, investigate (in order):

1. Managed-service provisioning time (inspect the run's per-step timestamps).
2. Retry/resume from a failed step inflating the total (attempt count > 1).
3. Region contention — the 30-min budget is a *normal cloud conditions* figure.
