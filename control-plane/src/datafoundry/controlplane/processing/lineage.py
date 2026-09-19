"""Lineage module (feature 003, T043).

Maintains end-to-end lineage source -> Bronze -> Silver -> Gold -> consumers,
navigable in both directions (FR-015, SC-006).
"""

from __future__ import annotations

import uuid

from datafoundry.controlplane.db.models import LineageLink
from sqlalchemy import select
from sqlalchemy.orm import Session


def get_lineage(session: Session, *, dataset_id: uuid.UUID) -> dict[str, list[dict]]:
    """Return a dataset's upstream + downstream lineage (FR-015).

    Navigable in both directions: upstream lists the datasets that feed this
    one; downstream lists the datasets this one feeds.
    """
    upstream = session.execute(
        select(LineageLink).where(LineageLink.target_dataset_id == dataset_id)
    ).scalars()
    downstream = session.execute(
        select(LineageLink).where(LineageLink.source_dataset_id == dataset_id)
    ).scalars()

    def _node(link: LineageLink, *, is_upstream: bool) -> dict:
        other = link.source_dataset if is_upstream else link.target_dataset
        return {
            "dataset_id": str(other.id),
            "layer": other.layer.value,
            "transformation_id": str(link.transformation_id) if link.transformation_id else None,
            "transformation_version": link.transformation_version,
        }

    return {
        "upstream": [_node(link, is_upstream=True) for link in upstream],
        "downstream": [_node(link, is_upstream=False) for link in downstream],
    }
