"""Processing engine core (feature 003, T010).

Runs a transformation -> transform (PyArrow/DuckDB) -> write Iceberg snapshot
(atomic per version, FR-012) -> run gate (feature 004) -> promote or block;
records ``DatasetVersion`` + ``PromotionState``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from datafoundry.controlplane.db.models import (
    Dataset,
    DatasetLayer,
    DatasetVersion,
    LayerTransition,
    PromotionStateRow,
    Transformation,
)
from datafoundry.controlplane.processing.promotion import transition
from datafoundry.controlplane.processing.transformations.registry import (
    resolve_transformation,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

#: Map target layer -> the gate transition that gates it (feature 004).
_TRANSITION_BY_TARGET = {
    DatasetLayer.bronze: LayerTransition.ingestion_to_bronze,
    DatasetLayer.silver: LayerTransition.bronze_to_silver,
    DatasetLayer.gold: LayerTransition.silver_to_gold,
}


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _next_version(session: Session, dataset_id: uuid.UUID) -> int:
    latest = session.execute(
        select(DatasetVersion.version)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    return (latest or 0) + 1


def _current_promotion(session: Session, dataset_id: uuid.UUID) -> PromotionStateRow | None:
    return session.execute(
        select(PromotionStateRow).where(PromotionStateRow.dataset_id == dataset_id)
    ).scalar_one_or_none()


def _find_gate(session: Session, dataset_id: uuid.UUID, transition: LayerTransition):
    """Latest gate for a dataset's layer transition (feature 004)."""
    from datafoundry.controlplane.db.models import QualityGate

    return session.execute(
        select(QualityGate)
        .where(
            QualityGate.dataset_id == dataset_id,
            QualityGate.transition == transition,
        )
        .order_by(QualityGate.config_version.desc())
        .limit(1)
    ).scalar_one_or_none()


def run_transformation(
    session: Session,
    *,
    gateway: Any,
    transformation_id: uuid.UUID,
    dataset_id: uuid.UUID,
    environment: str = "production",
    quality_gateway: Any | None = None,
) -> dict[str, Any]:
    """Execute a transformation against an input dataset.

    Reads the input dataset's current records, applies the transformation,
    writes an atomic snapshot to the target layer, runs the output dataset's
    quality gate (feature 004), and records the promotion state.

    Returns a dict matching processing-api.md §2 run response.
    """
    transformation = session.get(Transformation, transformation_id)
    if transformation is None:
        raise ValueError(f"no transformation {transformation_id}")
    input_dataset = session.get(Dataset, dataset_id)
    if input_dataset is None:
        raise ValueError(f"no dataset {dataset_id}")

    # Resolve the output dataset: same name in the target layer.
    output = session.execute(
        select(Dataset).where(
            Dataset.platform_id == input_dataset.platform_id,
            Dataset.name == input_dataset.name,
            Dataset.layer == transformation.target_layer,
        )
    ).scalar_one_or_none()
    if output is None:
        raise ValueError(
            f"no {transformation.target_layer.value} dataset '{input_dataset.name}' "
            f"for transformation {transformation.name}"
        )

    # Read input records.
    input_table = gateway.read_table(str(input_dataset.id), input_dataset.layer.value)

    # Apply the transformation.
    impl = resolve_transformation(transformation.logic_definition.get("type", ""))
    result = impl.apply(
        input_table=input_table,
        logic=dict(transformation.logic_definition or {}),
        dedup_keys=list(transformation.dedup_keys or []),
    )

    # Write an atomic snapshot (Iceberg-in-memory, FR-012).
    version = _next_version(session, output.id)
    table_ref = gateway.write_snapshot(
        dataset_id=str(output.id),
        layer=output.layer.value,
        schema=result.table.schema,
        rows=result.table.to_pylist(),
        version=version,
    )

    # Run the output dataset's gate (feature 004) if one exists.
    transition_enum = _TRANSITION_BY_TARGET[output.layer]
    gate = _find_gate(session, output.id, transition_enum)
    gate_report_id = None
    gate_passed = True
    if gate is not None:
        from datafoundry.controlplane.quality.engine import run_gate

        report = run_gate(
            session,
            gateway=quality_gateway or gateway,
            gate_id=gate.id,
            run_id=uuid.uuid4(),
            batch_id=uuid.uuid4(),
            environment=environment,
        )
        gate_report_id = report.id
        gate_passed = report.decision == "promote"

    # Record the version.
    version_row = DatasetVersion(
        dataset_id=output.id,
        version=version,
        transformation_id=transformation.id,
        input_versions={str(input_dataset.id): _current_version(session, input_dataset.id)},
        table_ref=table_ref,
        record_count=result.table.num_rows,
        quarantined_count=len(result.quarantined),
        gate_report_id=gate_report_id,
    )
    session.add(version_row)

    # Record quarantined records (FR-006).
    for i, row in enumerate(result.quarantined):
        gateway.write_quarantine(
            dataset_id=str(output.id),
            batch_id=str(version_row.id),
            payload_ref=f"{output.id}:{version}:{i}",
            meta={"reason": row.get("_reason", "malformed record")},
        )

    # Promote or block.
    current = _current_promotion(session, output.id)
    blocked_reason = None
    if not gate_passed:
        blocked_reason = f"gate {gate.id} failed for {output.name}"
    new_state = transition(
        current.state if current else None,
        gate_passed=gate_passed,
        target_layer=output.layer.value,
        blocked_reason=blocked_reason,
    )
    if current is None:
        session.add(
            PromotionStateRow(
                dataset_id=output.id,
                state=new_state,
                gate_report_id=gate_report_id,
                blocked_reason=blocked_reason,
            )
        )
    else:
        current.state = new_state
        current.gate_report_id = gate_report_id
        current.blocked_reason = blocked_reason
        current.transitioned_at = _utcnow()
    session.flush()

    return {
        "output_dataset_id": str(output.id),
        "output_version": version,
        "record_count": result.table.num_rows,
        "quarantined_count": len(result.quarantined),
        "gate_report_id": str(gate_report_id) if gate_report_id else None,
        "promotion_state": new_state.value,
    }


def _current_version(session: Session, dataset_id: uuid.UUID) -> int | None:
    return session.execute(
        select(DatasetVersion.version)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()
