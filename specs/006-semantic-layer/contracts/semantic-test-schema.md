# Contract: Semantic Test Schema

**Feature**: 006-semantic-layer | **Version**: v1 | **Date**: 2026-09-15

Declarative definition of a semantic test bound to a semantic model. Runs at publish time AND on schedule against production data (FR-014). A failing test blocks publication (FR-004).

## Schema

```yaml
tests:
  - name: revenue_calculation
    category: calculation
    parameters:
      reference_data: gold_orders_reference
      expected_value: 12345.67
      tolerance_pct: 0.5
  - name: revenue_reconciliation
    category: reconciliation
    parameters:
      source_dataset: gold_orders
      tolerance_pct: 0.5
  - name: orders_customer_relationship
    category: relationship
    parameters:
      relationship: orders_customer
      max_fanout: 1
  - name: revenue_filter
    category: filter
    parameters:
      filter: { order_status: COMPLETED }
      expected_count: 100
```

---

## Fields

| Field | Type | Required | Constraints | Notes |
|---|---|---|---|---|
| `tests` | list | yes | ≥1 | FR-004 |
| `tests[].name` | string | yes | unique per model | |
| `tests[].category` | enum | yes | `calculation`/`reconciliation`/`relationship`/`filter` | FR-004 |
| `tests[].parameters` | map | yes | category-specific | |

**Categories** (FR-004):
- `calculation` — metric produces expected result on reference data.
- `reconciliation` — aggregation reconciles with the underlying dataset.
- `relationship` — dimension relationships hold, no fan-out/double-counting (SC-007).
- `filter` — filters behave as defined.

**Validation rules**:
1. Schema conformance (strict Pydantic model).
2. Test names unique within the model.
3. Parameters valid for the category (e.g. `calculation` requires `reference_data` + `expected_value`; `relationship` requires `relationship` + `max_fanout`).
4. Secret-scan passes on the whole config.