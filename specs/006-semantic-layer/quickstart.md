# Quickstart: Semantic Layer

**Feature**: 006-semantic-layer | **Date**: 2026-09-15

Runnable validation scenarios proving the semantic layer works end to end. See [semantic-api.md](./contracts/semantic-api.md), [semantic-model-schema.md](./contracts/semantic-model-schema.md), [semantic-test-schema.md](./contracts/semantic-test-schema.md), and [data-model.md](./data-model.md) for details.

## Setup (local development)

- Feature 001 control plane running (see `specs/001-one-click-platform-deployment/quickstart.md`) — the API, a deployed platform with `storage_zones`/`catalog`/`secrets` capabilities, and the `datafoundry` CLI in the venv.
- Gold/Silver datasets produced by feature 003 and gated by feature 004 (e.g. `gold_orders`, `gold_customers`).
- Feature 005 access policies configured (classification, column protection, row-level restrictions).

```bash
cd control-plane && source .venv/bin/activate
```

---

## Scenario 1: Define a metric once, consume everywhere (US1, FR-001, FR-002)

Define a semantic model with a revenue metric:

```bash
datafoundry semantic model set --config configs/commerce-model.yaml
# config: domain commerce; metric revenue = sum(order_amount) where status COMPLETED;
#         dimensions customer, time; bound to gold_orders
```

**Expected**: `201` with `model_id` + `version: 1`, `certification_state: draft`.

Query the metric through two different consumption paths (analyst SQL + programmatic API):

```bash
datafoundry metric query <metric_id> --dimensions customer,time --filters '{"time":{"gte":"2026-01-01","lt":"2026-02-01"}}'
curl -X POST /api/v1/semantic/metrics/<metric_id>/query -d '{"dimensions":["customer","time"],"filters":{"time":{"gte":"2026-01-01","lt":"2026-02-01"}}}'
```

**Expected**:
1. Both paths return identical results (FR-002, SC-001).
2. Result carries `definition_version`, `dataset_versions`, `freshness`, `quality_state` (FR-008, FR-012).
3. `GET /semantic/metrics/{id}` shows plain-language definition, formula, owner, source datasets, lineage (US1-AC3).

---

## Scenario 2: Governed metric lifecycle (US2, FR-003, FR-004, FR-005)

Submit a metric change that fails a semantic test (e.g. aggregation no longer reconciles):

```bash
datafoundry semantic model set --config configs/commerce-model-v2.yaml   # breaking change
datafoundry semantic test run <test_id>                                   # reconciliation fails
datafoundry semantic model publish <model_id> --classification breaking
```

**Expected**: publication blocked `422` with failure detail (FR-004); the proposer is reported the failure.

Submit a correct change and publish:

```bash
datafoundry semantic model publish <model_id> --classification non_breaking
datafoundry semantic model approve <publication_id>
```

**Expected**: `201` pending → `200` approved + `published_at`; registered consumers notified of breaking changes (FR-005); previous version remains in history (US2-AC2).

Query "as of" a prior period:

```bash
datafoundry metric query <metric_id> --as-of 2026-08-01
```

**Expected**: result records the definition version used (FR-012, US2-AC3).

---

## Scenario 3: Access policies on semantic consumption (US3, FR-007, SC-005)

Query the same metric as two roles with different authorisations:

```bash
datafoundry metric query <metric_id> --as analytics@acme.com   # authorised
datafoundry metric query <metric_id> --as intern@acme.com      # unauthorised
```

**Expected**:
1. Unauthorised user over a RESTRICTED dataset → `403` with clear reason (US3-AC1).
2. Protected column values remain masked/tokenised per policy in results (US3-AC2, SC-005).
3. Row-level restrictions applied — results include only rows the user is authorised to see (US3-AC3).

---

## Scenario 4: Discover and understand business terms (US4, FR-011)

Search the catalog for a business term:

```bash
datafoundry semantic discovery --q "customer revenue"
```

**Expected**: the certified metric surfaces with definition, owner, quality score, freshness, lineage, consuming teams (US4-AC1). Draft definitions hidden from general users or clearly marked as draft (US4-AC2).

---

## Scenario 5: Deprecation (FR-010)

Deprecate a metric with a successor:

```bash
datafoundry semantic metric deprecate <metric_id> --successor <new_metric_id> --period 30
```

**Expected**: `certification_state: deprecated`, successor reference set, registered consumers notified (FR-010). Queries return a deprecation notice with results, or are refused after the deprecation period (FR-010).