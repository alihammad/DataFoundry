"""Semantic access-policy enforcement (feature 006, T031).

Role-based metric visibility, column-level protection preserved in results,
row-level restrictions applied; reuse feature 005 access module (FR-007).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from datafoundry.controlplane.api.errors import ForbiddenError
from datafoundry.controlplane.security.access import decide_access
from sqlalchemy.orm import Session


@dataclass
class AccessContext:
    """Enforced access decisions for a metric query (T031).

    - ``protected_columns``: columns whose values must be masked/tokenised
      per policy (US3-AC2, SC-005).
    - ``row_filters``: row-level predicates to apply for the caller's roles
      (US3-AC3).
    """

    protected_columns: list[str]
    row_filters: list[str]
    reason: str | None = None


def enforce_metric_access(
    session: Session,
    *,
    caller_identity: str,
    caller_roles: list[str],
    metric: Any,
    dataset: Any,
    gateway: Any,
) -> AccessContext:
    """Enforce role-based visibility + column/row protection (FR-007).

    - US3-AC1: 403 when the caller is not authorised for the metric's bound
      dataset classification (reuses feature 005 ``decide_access``).
    - US3-AC2: protected column values are masked/tokenised per policy.
    - US3-AC3: row-level restrictions are applied for the caller's roles.
    """
    # US3-AC1: role-based visibility over the bound dataset (FR-007).
    decision = decide_access(
        session,
        identity=caller_identity,
        resource=f"metric:{metric.id}",
        action="read",
        roles=caller_roles,
        dataset_id=dataset.id,
    )
    if decision.outcome == "denied":
        raise ForbiddenError(
            ["metric access"],
            detail=decision.reason or "caller not authorised for this metric (FR-007)",
        )

    # US3-AC2 / US3-AC3: column + row protection from the gateway metadata.
    meta = gateway.table_metadata(dataset.name, dataset.layer.value)
    protected_columns = list(meta.get("protected_columns", []))
    restrictions = meta.get("row_restrictions", {})
    row_filters: list[str] = []
    for role in caller_roles:
        row_filters.extend(restrictions.get(role, []))

    return AccessContext(
        protected_columns=protected_columns,
        row_filters=row_filters,
    )
