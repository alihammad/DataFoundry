# Contract: Semantic Model Schema

**Feature**: 006-semantic-layer | **Version**: v1 | **Date**: 2026-09-15

Declarative definition of a semantic model (metrics, dimensions, measures, relationships) for a domain. Validated by a strict Pydantic model (reusing the feature 004 `quality_schema.py` pattern); secret-scanned on every write (SC-007). Version controlled through GitOps (FR-003).

## Schema

```yaml
domain: commerce
metrics:
  - name: revenue
    business_definition: "Sum of order amount where order status is COMPLETED"
    formula:
      measure: order_amount
      aggregation: sum
      filter:
        order_status: COMPLETED
    dimensions: [customer, time]
    bound_datasets: [gold_orders]
    owner: analytics@acme.com
dimensions:
  - name: customer
    members: [customer_id, customer_name]
    protection_status: internal
  - name: time
    members: [order_date]
    protection_status: public
measures:
  - name: order_amount
    dataset: gold_orders
    column: amount
    data_type: numeric
relationships:
  - name: orders_customer
    left_dataset: gold_orders
    right_dataset: gold_customers
    join_key: customer_id
    join_type: inner
```

---

## Fields

| Field | Type | Required | Constraints | Notes |
|---|---|---|---|---|
| `domain` | string | yes | unique | business-term names unique per domain (FR-009) |
| `metrics` | list | yes | ≥1 | FR-001 |
| `metrics[].name` | string | yes | unique per model | business term (FR-009) |
| `metrics[].business_definition` | string | yes | | plain-language definition (FR-006) |
| `metrics[].formula` | map | yes | measure + aggregation + optional filter | compiles to DuckDB query (R-02) |
| `metrics[].dimensions` | list | yes | | FR-006 |
| `metrics[].bound_datasets` | list | yes | Gold/Silver dataset ids | FR-006 |
| `metrics[].owner` | string | yes | | FR-006 |
| `dimensions` | list | yes | | FR-001 |
| `dimensions[].name` | string | yes | unique per model | |
| `dimensions[].members` | list | yes | | |
| `dimensions[].protection_status` | enum | yes | `public`/`internal`/`confidential`/`restricted`/`highly_restricted` | from feature 005 (FR-007) |
| `measures` | list | yes | | FR-001 |
| `measures[].name` | string | yes | unique per model | |
| `measures[].dataset` | string | yes | source dataset | |
| `measures[].column` | string | yes | source column | |
| `measures[].data_type` | string | yes | | |
| `relationships` | list | no | | FR-001 |
| `relationships[].name` | string | yes | unique per model | |
| `relationships[].left_dataset` / `right_dataset` | string | yes | | joined datasets |
| `relationships[].join_key` | string | yes | | join column |
| `relationships[].join_type` | enum | yes | `inner`/`left`/`right`/`full` | |

**Validation rules** (all errors at once):
1. Schema conformance (strict Pydantic model).
2. Business-term names unique within the domain (FR-009).
3. Metric formula compiles to a valid query over its bound datasets (R-02).
4. Dimension/measure/relationship references resolve within the model.
5. Secret-scan passes on the whole config.