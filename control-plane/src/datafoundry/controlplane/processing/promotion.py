"""Promotion state machine (feature 003, T009).

Transitions ``INGESTED -> ... -> CONSUMABLE`` only on a passing quality gate
(feature 004); a failed gate leaves the dataset ``blocked`` at the failed
layer. Overrides are scoped to the specific blocked run.
"""

from __future__ import annotations

from datafoundry.controlplane.db.models import PromotionState

#: Ordered promotion path (FR-007, constitution III).
PROMOTION_ORDER: list[PromotionState] = [
    PromotionState.ingested,
    PromotionState.ingestion_validated,
    PromotionState.bronze,
    PromotionState.bronze_validated,
    PromotionState.silver,
    PromotionState.silver_validated,
    PromotionState.gold,
    PromotionState.gold_validated,
    PromotionState.consumable,
]

#: The layer-validated state that gates the next layer's promotion.
_VALIDATED_BY_LAYER = {
    "bronze": PromotionState.bronze_validated,
    "silver": PromotionState.silver_validated,
    "gold": PromotionState.gold_validated,
}


def next_state(current: PromotionState) -> PromotionState | None:
    """The next state after ``current`` in the promotion path (or None)."""
    try:
        idx = PROMOTION_ORDER.index(current)
    except ValueError:
        return None
    if idx + 1 >= len(PROMOTION_ORDER):
        return None
    return PROMOTION_ORDER[idx + 1]


def layer_validated_state(layer: str) -> PromotionState:
    """The validated state for a layer (e.g. bronze -> bronze_validated)."""
    return _VALIDATED_BY_LAYER[layer]


def can_promote_to_layer(current: PromotionState, target_layer: str) -> bool:
    """Whether ``current`` permits promotion into ``target_layer``.

    A dataset may be promoted into a layer only when the layer below it is
    validated (e.g. bronze_validated gates silver). Bronze is the entry layer
    (ingestion_validated gates bronze).
    """
    required = {
        "bronze": PromotionState.ingestion_validated,
        "silver": PromotionState.bronze_validated,
        "gold": PromotionState.silver_validated,
    }[target_layer]
    return current == required


def transition(
    current: PromotionState | None,
    *,
    gate_passed: bool,
    target_layer: str,
    blocked_reason: str | None = None,
) -> PromotionState:
    """Compute the next promotion state given a gate decision.

    - ``gate_passed`` True: advance to the layer's validated state (or the
      next state in the path for the entry layer).
    - ``gate_passed`` False: return ``blocked`` with the reason.
    """
    if not gate_passed:
        return PromotionState.blocked
    if current is None:
        # Entry: ingestion_validated gates bronze; a fresh silver/gold dataset
        # with a passing gate lands at its layer-validated state.
        if target_layer == "bronze":
            return PromotionState.bronze
        return layer_validated_state(target_layer)
    if target_layer == "bronze":
        return PromotionState.bronze_validated
    return layer_validated_state(target_layer)
