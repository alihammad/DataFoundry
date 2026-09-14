"""API router: pre-flight validation (T037, contracts/deployment-api.md §3).

``POST /api/v1/validate`` — validate a config with NO side effects (SC-004):
``200 {"valid": true}`` or the same all-errors 422 body as POST /platforms.
"""

from __future__ import annotations

from typing import Any

from datafoundry.controlplane.api.deps import get_db, get_settings_from_app
from datafoundry.controlplane.api.errors import ConfigValidationError
from datafoundry.controlplane.api.platforms import _cloud_scope_id, _existing_names
from datafoundry.controlplane.capabilities.registry import default_registry
from datafoundry.controlplane.config.settings import Settings
from datafoundry.controlplane.config.validation import validate_platform_config
from datafoundry.controlplane.providers.base import default_providers
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

router = APIRouter(tags=["validate"])


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any]


class ValidateResponse(BaseModel):
    valid: bool


@router.post("/validate", response_model=ValidateResponse)
def validate_config(
    body: ValidateRequest,
    session: Session = Depends(get_db),
    settings: Settings = Depends(get_settings_from_app),
) -> ValidateResponse:
    platform_section = body.config.get("platform")
    provider = platform_section.get("provider") if isinstance(platform_section, dict) else None
    result = validate_platform_config(
        body.config,
        providers=default_providers,
        registry=default_registry,
        existing_names=_existing_names(session),
        cloud_scope_id=_cloud_scope_id(settings, provider if isinstance(provider, str) else None),
    )
    if not result.valid:
        raise ConfigValidationError(result.error_dicts())
    return ValidateResponse(valid=True)
