"""RFC 9457 problem+json error handling (T017).

Every API error is returned as ``application/problem+json`` with the standard
members (type, title, status, detail) plus contract-specific extensions
(``errors`` list for 422 validation, ``code``/``scope`` for 409,
``code``/``missing`` for 403 — see contracts/deployment-api.md).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

PROBLEM_CONTENT_TYPE = "application/problem+json"
ERROR_TYPE_BASE = "https://datafoundry.example/errors"


class ApiError(Exception):
    """Base for contract errors rendered as RFC 9457 problem+json."""

    status_code: int = 500
    error_type: str = "internal"
    title: str = "Internal error"

    def __init__(self, detail: str = "", **extensions: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        self.extensions = extensions

    def to_problem(self) -> dict[str, Any]:
        problem: dict[str, Any] = {
            "type": f"{ERROR_TYPE_BASE}/{self.error_type}",
            "title": self.title,
            "status": self.status_code,
            "detail": self.detail,
        }
        problem.update(self.extensions)
        return problem


class ConfigValidationError(ApiError):
    """422 with ALL errors at once (FR-003, SC-004).

    ``errors`` entries: ``{path, code, message, remediation}``.
    """

    status_code = 422
    error_type = "validation"
    title = "Configuration validation failed"

    def __init__(self, errors: list[dict[str, str]]) -> None:
        super().__init__("One or more configuration validation errors", errors=errors)
        self.errors = errors


class ConflictError(ApiError):
    """409 — e.g. duplicate platform name in cloud scope (FR-013)."""

    status_code = 409
    error_type = "conflict"
    title = "Conflict"

    def __init__(self, code: str, detail: str, **extensions: Any) -> None:
        super().__init__(detail, code=code, **extensions)


class ForbiddenError(ApiError):
    """403 — missing cloud permissions with precise list (FR-018)."""

    status_code = 403
    error_type = "insufficient_permissions"
    title = "Insufficient permissions"

    def __init__(self, missing: list[str], detail: str = "") -> None:
        super().__init__(
            detail or "Caller lacks required cloud permissions",
            code="insufficient_permissions",
            missing=missing,
        )


class NotFoundError(ApiError):
    status_code = 404
    error_type = "not_found"
    title = "Resource not found"


def _problem_response(problem: dict[str, Any], status: int) -> JSONResponse:
    return JSONResponse(status_code=status, content=problem, media_type=PROBLEM_CONTENT_TYPE)


def _pydantic_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Translate Pydantic v2 errors to the contract error shape."""
    errors = []
    for err in exc.errors():
        path = ".".join(str(loc) for loc in err["loc"]) or "$"
        errors.append(
            {
                "path": path,
                "code": err.get("type", "invalid_value"),
                "message": err.get("msg", "invalid value"),
                "remediation": _remediation_for(err),
            }
        )
    return errors


def _remediation_for(err: dict[str, Any]) -> str:
    err_type = err.get("type", "")
    ctx = err.get("ctx") or {}
    if err_type == "extra_forbidden":
        return "Remove the unknown field (schema is strict)"
    if err_type in ("missing", "value_error"):
        return str(ctx.get("error") or err.get("msg") or "Provide the required value")
    if err_type.startswith("enum") or err_type == "literal_error":
        allowed = ctx.get("expected")
        return f"Use one of the allowed values: {allowed}" if allowed else "Use an allowed value"
    return "Correct the value per contracts/platform-config-schema.md"


def register_error_handlers(app: FastAPI) -> None:
    """Install problem+json handlers on the FastAPI app."""

    @app.exception_handler(ApiError)
    async def _api_problem_handler(_: Request, exc: ApiError) -> JSONResponse:
        return _problem_response(exc.to_problem(), exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _request_validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {
                "path": ".".join(str(loc) for loc in err["loc"]) or "$",
                "code": err.get("type", "invalid_value"),
                "message": err.get("msg", "invalid value"),
                "remediation": _remediation_for(err),
            }
            for err in exc.errors()
        ]
        problem = ConfigValidationError(errors).to_problem()
        return _problem_response(problem, 422)

    @app.exception_handler(ValidationError)
    async def _validation_error_handler(_: Request, exc: ValidationError) -> JSONResponse:
        problem = ConfigValidationError(_pydantic_errors(exc)).to_problem()
        return _problem_response(problem, 422)

    @app.exception_handler(404)
    async def _not_found_handler(request: Request, _: Any) -> JSONResponse:
        problem = NotFoundError(f"No route for {request.url.path}").to_problem()
        return _problem_response(problem, 404)

    @app.exception_handler(Exception)
    async def _unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        # Never leak internals (and never secrets — SC-006): generic detail.
        problem = ApiError("An unexpected error occurred").to_problem()
        return _problem_response(problem, 500)
