"""API router: semantic tests (T027, contracts/semantic-api.md §3).

- ``POST /semantic/models/{id}/tests`` — define a semantic test (FR-004):
  201 test_id.
- ``POST /semantic/tests/{id}/run`` — run a semantic test: 200 passed/failed.
"""

from __future__ import annotations

import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db
from datafoundry.controlplane.api.errors import (
    ConfigValidationError,
    NotFoundError,
)
from datafoundry.controlplane.audit.service import AuditService
from datafoundry.controlplane.config.semantic_schema import (
    SemanticConfigError,
    validate_semantic_tests,
)
from datafoundry.controlplane.db.models import (
    SemanticModel,
    SemanticTest,
    SemanticTestResult,
)
from datafoundry.controlplane.semantic.tests.registry import (
    UnknownSemanticTestCategoryError,
    resolve_test,
)
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

router = APIRouter(tags=["semantic-tests"])


class TestDefined(BaseModel):
    test_id: uuid.UUID


class TestRunResult(BaseModel):
    test_id: uuid.UUID
    status: str
    measured_value: dict[str, Any] | None


def _get_test(session: Session, test_id: uuid.UUID) -> SemanticTest:
    test = session.get(SemanticTest, test_id)
    if test is None:
        raise NotFoundError(f"no semantic test with id {test_id}")
    return test


@router.post("/semantic/models/{model_id}/tests", status_code=201, response_model=TestDefined)
def define_semantic_test(
    model_id: uuid.UUID,
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> TestDefined:
    """Define a semantic test (FR-004)."""
    model = session.get(SemanticModel, model_id)
    if model is None:
        raise NotFoundError(f"no semantic model with id {model_id}")
    try:
        definition = validate_semantic_tests(body)
    except SemanticConfigError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": _error_path(msg),
                    "code": "invalid_value",
                    "message": msg,
                    "remediation": (
                        "Correct the semantic test per contracts/semantic-test-schema.md"
                    ),
                }
                for msg in exc.errors
            ]
        ) from exc
    spec = definition.tests[0]
    test = SemanticTest(
        model_id=model.id,
        name=spec.name,
        category=spec.category,
        parameters=spec.parameters,
    )
    session.add(test)
    session.flush()
    return TestDefined(test_id=test.id)


@router.post("/semantic/tests/{test_id}/run", response_model=TestRunResult)
def run_semantic_test(
    test_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> TestRunResult:
    """Run a semantic test (FR-004, FR-014)."""
    test = _get_test(session, test_id)
    try:
        impl_cls = resolve_test(test.category.value)
    except UnknownSemanticTestCategoryError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": "category",
                    "code": "invalid_value",
                    "message": str(exc),
                    "remediation": "Use a registered semantic test category",
                }
            ]
        ) from exc
    impl = impl_cls(
        name=test.name,
        category=test.category.value,
        parameters=dict(test.parameters or {}),
    )
    result = impl.evaluate(None, gateway=None)
    session.add(
        SemanticTestResult(
            test_id=test.id,
            status=result.status,
            measured_value=result.measured_value,
            trigger="publish",
        )
    )
    AuditService(session).semantic_test_run(
        actor=caller.identity, test_id=test.id, status=result.status.value
    )
    session.flush()
    return TestRunResult(
        test_id=test.id,
        status=result.status.value,
        measured_value=result.measured_value,
    )


def _error_path(msg: str) -> str:
    return msg.split(":", 1)[0] if ":" in msg else "$"
