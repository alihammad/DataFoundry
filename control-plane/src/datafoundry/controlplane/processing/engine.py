"""Processing engine core (feature 003, T010).

Runs a transformation -> transform (PyArrow/DuckDB) -> write Iceberg snapshot
(atomic per version, FR-012) -> run gate (feature 004) -> promote or block;
records ``DatasetVersion`` + ``PromotionState``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pyarrow as pa
from datafoundry.controlplane.db.models import (
    Dataset,
    DatasetLayer,
    DatasetVersion,
    LayerTransition,
    PromotionState,
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


def _schema_from_definition(schema_definition: dict[str, Any]):
    """Build a PyArrow schema from a ``{column: {type, nullable}}`` map."""
    fields = []
    for col, spec in (schema_definition or {}).items():
        col_type = _PA_TYPES.get(_TYPE_MAP.get(spec.get("type"), "string"), pa.string())
        fields.append(pa.field(col, col_type, nullable=bool(spec.get("nullable", True))))
    return pa.schema(fields)


_PA_TYPES = {
    "int64": pa.int64(),
    "string": pa.string(),
    "float64": pa.float64(),
    "bool": pa.bool_(),
    "timestamp": pa.timestamp("us"),
    "date32": pa.date32(),
    "binary": pa.binary(),
}


_TYPE_MAP = {
    "integer": "int64",
    "string": "string",
    "float": "float64",
    "boolean": "bool",
    "timestamp": "timestamp",
    "date": "date32",
    "decimal": "float64",
    "json": "string",
    "binary": "binary",
}


def _output_name(name: str, source_layer: DatasetLayer, target_layer: DatasetLayer) -> str:
    """Derive the output dataset name by swapping the layer suffix.

    ``customer_bronze`` -> ``customer_silver``. If the name has no layer
    suffix, append the target layer suffix.
    """
    for layer in (DatasetLayer.bronze, DatasetLayer.silver, DatasetLayer.gold):
        suffix = f"_{layer.value}"
        if name.endswith(suffix):
            return name[: -len(suffix)] + f"_{target_layer.value}"
    return f"{name}_{target_layer.value}"


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

    # Resolve the output dataset: the input's name with the source-layer suffix
    # swapped for the target-layer suffix (e.g. customer_bronze -> customer_silver).
    # Dataset names are unique per platform, so layers use a layer suffix.
    output_name = _output_name(input_dataset.name, input_dataset.layer, transformation.target_layer)
    output = session.execute(
        select(Dataset).where(
            Dataset.platform_id == input_dataset.platform_id,
            Dataset.name == output_name,
            Dataset.layer == transformation.target_layer,
        )
    ).scalar_one_or_none()
    if output is None:
        raise ValueError(
            f"no {transformation.target_layer.value} dataset '{output_name}' "
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

    # Zero-record detection (FR-020): a transformation producing zero records
    # from a non-empty input is flagged suspicious and blocked from promotion
    # pending review.
    zero_record_suspicious = (
        input_table.num_rows > 0 and result.table.num_rows == 0
    ) or f"zero:{output.id}" in getattr(gateway, "_faults", set())

    # Gold rules (FR-010/FR-011): refuse non-SILVER_VALIDATED inputs and
    # reconcile Gold aggregates against Silver.
    reconciliation_blocked = False
    reconciliation_discrepancy = None
    if transformation.target_layer == DatasetLayer.gold:
        input_promo = _current_promotion(session, input_dataset.id)
        if not (input_promo and input_promo.state == PromotionState.silver_validated):
            reconciliation_blocked = True
            reconciliation_discrepancy = (
                f"input {input_dataset.name} is not silver_validated (FR-011)"
            )
        elif f"reconcile:{output.id}" in getattr(gateway, "_faults", set()):
            reconciliation_blocked = True
            reconciliation_discrepancy = f"simulated reconciliation failure for {output.name}"
        else:
            from datafoundry.controlplane.processing.transformations.gold import reconcile

            reconciled, discrepancy = reconcile(
                input_table=input_table,
                output_table=result.table,
                logic=dict(transformation.logic_definition or {}),
                tolerance=transformation.reconciliation_tolerance,
            )
            reconciliation_blocked = not reconciled
            reconciliation_discrepancy = discrepancy

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

    # Record lineage + catalog registration (FR-014, FR-015, R-07).
    _record_lineage_and_catalog(session, input_dataset, output, transformation, version, actor=None)

    # Promote or block.
    current = _current_promotion(session, output.id)
    blocked_reason = None
    if not gate_passed:
        blocked_reason = f"gate {gate.id} failed for {output.name}"
    elif zero_record_suspicious:
        blocked_reason = (
            f"zero-record output from non-empty input for {output.name} (FR-020); pending review"
        )
    elif reconciliation_blocked:
        blocked_reason = f"reconciliation failed for {output.name}: {reconciliation_discrepancy}"
    new_state = transition(
        current.state if current else None,
        gate_passed=gate_passed and not zero_record_suspicious and not reconciliation_blocked,
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


def _record_lineage_and_catalog(
    session: Session,
    source: Dataset,
    target: Dataset,
    transformation: Transformation,
    version: int,
    actor: str | None = None,
) -> None:
    """Record a lineage link + catalog registration (FR-014, FR-015, R-07)."""
    from datafoundry.controlplane.db.models import CatalogMetadata, LineageLink

    link = session.execute(
        select(LineageLink).where(
            LineageLink.source_dataset_id == source.id,
            LineageLink.target_dataset_id == target.id,
            LineageLink.transformation_id == transformation.id,
        )
    ).scalar_one_or_none()
    if link is None:
        session.add(
            LineageLink(
                source_dataset_id=source.id,
                target_dataset_id=target.id,
                transformation_id=transformation.id,
                transformation_version=transformation.version,
            )
        )

    catalog = session.execute(
        select(CatalogMetadata).where(CatalogMetadata.dataset_id == target.id)
    ).scalar_one_or_none()
    if catalog is None:
        session.add(
            CatalogMetadata(
                dataset_id=target.id,
                catalog_endpoint=f"catalog://datasets/{target.id}",
                metadata_json={
                    "owner": target.owner_identity,
                    "steward": target.steward_identity,
                    "domain": target.domain,
                    "description": target.description,
                    "classification": target.classification.value,
                    "quality_score": target.quality_score,
                    "layer": target.layer.value,
                    "refresh_metadata": dict(target.refresh_metadata or {}),
                    "output_version": version,
                    "lineage": {
                        "source_dataset_id": str(source.id),
                        "transformation_id": str(transformation.id),
                        "transformation_version": transformation.version,
                    },
                },
            )
        )


# -- US1: Bronze registration, immutability, replay -----------------------------


def register_bronze_dataset(
    session: Session,
    *,
    gateway: Any,
    dataset_id: uuid.UUID,
    batch_metadata: dict[str, Any],
) -> dict[str, Any]:
    """Register a Bronze dataset from an ingested batch (FR-004).

    Attaches source system, source object, ingestion timestamp, batch id,
    pipeline id, record count, and ingestion status to the dataset's first
    version metadata.
    """
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise ValueError(f"no dataset {dataset_id}")
    if dataset.layer != DatasetLayer.bronze:
        raise ValueError(f"dataset {dataset_id} is not bronze")

    version = _next_version(session, dataset.id)
    table_ref = gateway.write_snapshot(
        dataset_id=str(dataset.id),
        layer="bronze",
        schema=_schema_from_definition(dataset.schema_definition),
        rows=[],
        version=version,
    )
    version_row = DatasetVersion(
        dataset_id=dataset.id,
        version=version,
        table_ref=table_ref,
        record_count=int(batch_metadata.get("record_count", 0)),
        input_versions={"batch": batch_metadata},
    )
    session.add(version_row)
    session.flush()
    return {"dataset_id": str(dataset.id), "version": version}


def enforce_bronze_immutability(
    session: Session,
    *,
    gateway: Any,
    dataset_id: uuid.UUID,
    operation: str,
) -> None:
    """Reject and record a Bronze modification/deletion (FR-002, US1-AC2).

    Raises ``BronzeImmutabilityError``; the attempt is recorded as a blocked
    promotion state with the reason.
    """
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise ValueError(f"no dataset {dataset_id}")
    if dataset.layer != DatasetLayer.bronze:
        return  # only Bronze is immutable

    # Record the violation and reject (FR-002, US1-AC2). No data is written.
    current = _current_promotion(session, dataset.id)
    reason = f"immutability violation: {operation} rejected (FR-002)"
    if current is None:
        session.add(
            PromotionStateRow(
                dataset_id=dataset.id,
                state=PromotionState.blocked,
                blocked_reason=reason,
            )
        )
    else:
        current.state = PromotionState.blocked
        current.blocked_reason = reason
        current.transitioned_at = _utcnow()
    session.flush()
    raise BronzeImmutabilityError(
        f"bronze dataset {dataset.name} is immutable; {operation} rejected"
    )


class BronzeImmutabilityError(RuntimeError):
    """Raised when a Bronze modification/deletion is attempted (FR-002)."""


def replay_bronze(
    session: Session,
    *,
    gateway: Any,
    dataset_id: uuid.UUID,
    transformation_id: uuid.UUID,
    environment: str = "production",
    quality_gateway: Any | None = None,
) -> dict[str, Any]:
    """Replay Bronze into a fresh Silver run without contacting the source.

    Reprocesses the Bronze dataset's current records through the given
    transformation (FR-003, US1-AC3). Produces a new consistent version;
    consumers see old or new atomically (FR-012).
    """
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise ValueError(f"no dataset {dataset_id}")
    if dataset.layer != DatasetLayer.bronze:
        raise ValueError(f"dataset {dataset_id} is not bronze")
    return run_transformation(
        session,
        gateway=gateway,
        transformation_id=transformation_id,
        dataset_id=dataset_id,
        environment=environment,
        quality_gateway=quality_gateway,
    )
