"""Semantic model composition + validation (feature 006, T017).

Build a :class:`SemanticModel` from validated config; resolve
metric/dimension/measure/relationship references.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from datafoundry.controlplane.config.semantic_schema import (
    SemanticModelDefinition,
    validate_semantic_model,
)
from datafoundry.controlplane.db.models import (
    CertificationState,
    Dimension,
    Measure,
    Metric,
    Relationship,
    SecurityLevel,
    SemanticModel,
)
from sqlalchemy.orm import Session


class SemanticModelError(ValueError):
    """Raised when a semantic model cannot be composed."""


@dataclass
class ComposedModel:
    """A validated semantic model ready for persistence (T017)."""

    model: SemanticModel
    metrics: list[Metric] = field(default_factory=list)
    dimensions: list[Dimension] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)


def compose_semantic_model(
    session: Session,
    *,
    config: dict,
    created_by: str,
    yaml_text: str | None = None,
) -> ComposedModel:
    """Validate a semantic-model config and compose the ORM objects (T017).

    Resolves metric/dimension/measure/relationship references and binds
    measures to their source datasets. The model is created as ``draft``
    (FR-006); publication flows through GitOps (Phase 4).
    """
    definition = validate_semantic_model(config, yaml_text=yaml_text)

    config_hash = hashlib.sha256((yaml_text or "").encode()).hexdigest()
    model = SemanticModel(
        domain=definition.domain,
        version=1,
        config_yaml=yaml_text or "",
        config_hash=config_hash,
        certification_state=CertificationState.draft,
        created_by=created_by,
    )
    session.add(model)
    session.flush()

    # Resolve dataset ids by name (bound_datasets reference dataset names).
    dataset_ids = _resolve_dataset_ids(session, definition)

    measures = [
        Measure(
            model_id=model.id,
            name=m.name,
            dataset_id=dataset_ids[m.dataset],
            column=m.column,
            data_type=m.data_type,
        )
        for m in definition.measures
    ]
    session.add_all(measures)
    session.flush()

    dimensions = [
        Dimension(
            model_id=model.id,
            name=d.name,
            members=d.members,
            protection_status=SecurityLevel(d.protection_status),
        )
        for d in definition.dimensions
    ]
    session.add_all(dimensions)
    session.flush()

    relationships = [
        Relationship(
            model_id=model.id,
            name=r.name,
            left_dataset_id=dataset_ids[r.left_dataset],
            right_dataset_id=dataset_ids[r.right_dataset],
            join_key=r.join_key,
            join_type=r.join_type,
        )
        for r in definition.relationships
    ]
    session.add_all(relationships)
    session.flush()

    metrics = [
        Metric(
            model_id=model.id,
            name=m.name,
            business_definition=m.business_definition,
            formula=m.formula.model_dump(),
            dimensions=m.dimensions,
            bound_datasets=m.bound_datasets,
            owner_identity=m.owner,
        )
        for m in definition.metrics
    ]
    session.add_all(metrics)
    session.flush()

    return ComposedModel(
        model=model,
        metrics=metrics,
        dimensions=dimensions,
        measures=measures,
        relationships=relationships,
    )


def _resolve_dataset_ids(
    session: Session, definition: SemanticModelDefinition
) -> dict[str, uuid.UUID]:
    """Resolve dataset names referenced by measures/relationships to ids."""
    from datafoundry.controlplane.db.models import Dataset

    names = {m.dataset for m in definition.measures}
    for r in definition.relationships:
        names.add(r.left_dataset)
        names.add(r.right_dataset)
    rows = session.query(Dataset).filter(Dataset.name.in_(names)).all()
    by_name = {d.name: d.id for d in rows}
    missing = names - set(by_name)
    if missing:
        raise SemanticModelError(f"unknown dataset(s): {', '.join(sorted(missing))}")
    return by_name
