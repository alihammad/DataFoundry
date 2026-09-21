"""Semantic GitOps lifecycle (feature 006, T026).

propose -> validate -> approve -> publish; classify breaking/non-breaking;
breaking requires approval + consumer notification (FR-005). Reuses the
feature 001 ``config/gitops.py`` provenance pattern.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from datafoundry.controlplane.db.models import (
    ApprovalStatus,
    ChangeClassification,
    Publication,
    SemanticModel,
    SemanticTest,
    SemanticTestResult,
    SemanticTestStatus,
)
from sqlalchemy import select
from sqlalchemy.orm import Session


class PublicationBlockedError(ValueError):
    """Raised when a publication is blocked by failed semantic tests (FR-004)."""

    def __init__(self, failures: list[dict]) -> None:
        self.failures = failures
        super().__init__("publication blocked by failed semantic tests (FR-004)")


class PublicationNotFoundError(KeyError):
    """Raised when a publication id does not exist."""


@dataclass
class PublicationResult:
    """The outcome of a publication proposal/approval."""

    publication_id: uuid.UUID
    approval_status: str
    published_at: str | None = None


def propose_publication(
    session: Session,
    *,
    model_id: uuid.UUID,
    change_classification: ChangeClassification,
    proposed_by: str,
    gateway: object | None = None,
) -> PublicationResult:
    """Propose a publication of a semantic model version (FR-003, FR-004).

    Runs the model's semantic tests; a failing test blocks publication with
    failure detail (FR-004). Breaking changes require approval (FR-005).
    """
    model = session.get(SemanticModel, model_id)
    if model is None:
        raise PublicationNotFoundError(f"no semantic model with id {model_id}")

    # Run semantic tests; block on failures (FR-004).
    failures = _run_tests(session, model_id, gateway=gateway)
    if failures:
        raise PublicationBlockedError(failures)

    publication = Publication(
        model_id=model.id,
        version=model.version,
        change_classification=change_classification,
        approval_status=ApprovalStatus.pending,
    )
    session.add(publication)
    session.flush()
    return PublicationResult(
        publication_id=publication.id,
        approval_status=publication.approval_status.value,
    )


def approve_publication(
    session: Session,
    *,
    publication_id: uuid.UUID,
    approved_by: str,
) -> PublicationResult:
    """Approve a publication (FR-005). Marks the model published."""
    publication = session.get(Publication, publication_id)
    if publication is None:
        raise PublicationNotFoundError(f"no publication with id {publication_id}")
    publication.approval_status = ApprovalStatus.approved
    publication.approved_by = approved_by
    from datetime import UTC, datetime

    publication.published_at = datetime.now(UTC)
    session.flush()

    model = session.get(SemanticModel, publication.model_id)
    if model is not None:
        from datafoundry.controlplane.db.models import CertificationState

        model.certification_state = CertificationState.published
        session.flush()

    return PublicationResult(
        publication_id=publication.id,
        approval_status=publication.approval_status.value,
        published_at=publication.published_at.isoformat() if publication.published_at else None,
    )


def list_publications(session: Session, *, model_id: uuid.UUID) -> list[Publication]:
    """List a model's publication history (US2-AC2)."""
    return list(
        session.scalars(
            select(Publication)
            .where(Publication.model_id == model_id)
            .order_by(Publication.created_at.desc())
        ).all()
    )


def _run_tests(
    session: Session, model_id: uuid.UUID, *, gateway: object | None = None
) -> list[dict]:
    """Run all semantic tests for a model; return failure details (FR-004).

    For calculation/reconciliation tests, computes the metric's actual value
    via the gateway so the test compares against real data (FR-014).
    """
    from datafoundry.controlplane.semantic.tests.registry import resolve_test

    tests = session.scalars(select(SemanticTest).where(SemanticTest.model_id == model_id)).all()
    failures: list[dict] = []
    for test in tests:
        impl_cls = resolve_test(test.category.value)
        impl = impl_cls(
            name=test.name,
            category=test.category.value,
            parameters=dict(test.parameters or {}),
        )
        context = _test_context(session, model_id, test, gateway)
        result = impl.evaluate(None, gateway=gateway, **context)
        session.add(
            SemanticTestResult(
                test_id=test.id,
                status=result.status,
                measured_value=result.measured_value,
                trigger="publish",
            )
        )
        if result.status != SemanticTestStatus.passed:
            failures.append(
                {"test_id": str(test.id), "name": test.name, "measured": result.measured_value}
            )
    session.flush()
    return failures


def _test_context(
    session: Session, model_id: uuid.UUID, test: SemanticTest, gateway: object | None
) -> dict:
    """Compute the actual value/count context for a semantic test (FR-014)."""
    from datafoundry.controlplane.db.models import Measure, Metric
    from datafoundry.controlplane.semantic.compute.engine import compute_metric

    if gateway is None:
        return {}
    metric = session.execute(select(Metric).where(Metric.model_id == model_id)).scalars().first()
    if metric is None:
        return {}
    formula = metric.formula or {}
    measure = session.execute(
        select(Measure).where(Measure.model_id == model_id, Measure.name == formula.get("measure"))
    ).scalar_one_or_none()
    if measure is None:
        return {}
    from datafoundry.controlplane.db.models import Dataset

    dataset = session.get(Dataset, measure.dataset_id)
    dataset_name = dataset.name if dataset else str(measure.dataset_id)
    try:
        result = compute_metric(
            gateway=gateway,
            dataset=dataset_name,
            layer=dataset.layer.value if dataset else "gold",
            measure_column=measure.column,
            aggregation=formula.get("aggregation", "sum"),
            filter_spec=formula.get("filter"),
            dimensions=[],
            definition_version=1,
        )
    except Exception:
        return {}
    return {"actual_value": result.value, "expected_value": test.parameters.get("expected_value")}
