"""API router: ingestion config (T021, contracts/ingestion-api.md §2).

- ``POST /sources/{id}/config`` — create/update an ingestion config (FR-002):
  validate (all errors at once) -> version -> auto-create pipeline -> 201
  {config_id, version, pipeline_id}. 422 on invalid schedule /
  incremental-without-cursor / secret-scan hit.
- ``GET /sources/{id}/config`` — export the canonical YAML (FR-017):
  version/config_yaml/config_hash; no plaintext secrets (SC-007).
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
from datafoundry.controlplane.config.ingestion_schema import (
    IngestionConfigError,
    validate_ingestion_config,
)
from datafoundry.controlplane.config.validation import canonical_yaml
from datafoundry.controlplane.db.models import (
    DataSource,
    IngestionConfig,
    IngestionMode,
    IngestionPipeline,
    SourceType,
    TargetZone,
)
from datafoundry.controlplane.ingestion.engine import sha256_hex
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["ingestion-configs"])


# -- response models ------------------------------------------------------------


class ConfigCreated(BaseModel):
    config_id: uuid.UUID
    version: int
    pipeline_id: uuid.UUID


class ConfigExport(BaseModel):
    version: int
    config_yaml: str
    config_hash: str


# -- helpers ---------------------------------------------------------------------


def _get_source(session: Session, source_id: uuid.UUID) -> DataSource:
    source = session.get(DataSource, source_id)
    if source is None:
        raise NotFoundError(f"no source with id {source_id}")
    return source


def _next_version(session: Session, source_id: uuid.UUID) -> int:
    latest = session.execute(
        select(IngestionConfig.version)
        .where(IngestionConfig.source_id == source_id)
        .order_by(IngestionConfig.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    return (latest or 0) + 1


def _pipeline_name(source_name: str, config_name: str) -> str:
    """Derive a pipeline name from the source + config (lowercase, hyphenated)."""
    base = f"{source_name}-{config_name}"
    return base[:63].lower()


# -- routes ----------------------------------------------------------------------


@router.post(
    "/sources/{source_id}/config",
    status_code=201,
    response_model=ConfigCreated,
)
def create_ingestion_config(
    source_id: uuid.UUID,
    body: dict[str, Any],
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ConfigCreated:
    """Create/update an ingestion config; auto-creates the pipeline (FR-002)."""
    source = _get_source(session, source_id)

    config_yaml = canonical_yaml(body)
    try:
        config = validate_ingestion_config(body, yaml_text=config_yaml)
    except IngestionConfigError as exc:
        raise ConfigValidationError(
            [
                {
                    "path": _error_path(msg),
                    "code": "invalid_value",
                    "message": msg,
                    "remediation": (
                        "Correct the ingestion config per contracts/source-config-schema.md"
                    ),
                }
                for msg in exc.errors
            ]
        ) from exc

    # Rule 2: source.type must match the registered source's type.
    if config.source.type != source.type.value:
        raise ConfigValidationError(
            [
                {
                    "path": "source.type",
                    "code": "invalid_value",
                    "message": (
                        f"config source.type '{config.source.type}' does not match "
                        f"registered source type '{source.type.value}'"
                    ),
                    "remediation": "Use the registered source type",
                }
            ]
        )

    version = _next_version(session, source.id)
    is_new = version == 1

    ingestion_config = IngestionConfig(
        source_id=source.id,
        version=version,
        config_yaml=config_yaml,
        config_hash=sha256_hex(config_yaml.encode()),
        source_type=SourceType(config.source.type),
        selected_objects=_selected_objects(config),
        ingestion_mode=_ingestion_mode(config),
        schedule=config.schedule,
        target_zone=TargetZone(config.target.zone),
        validation_settings={
            "reconciliation_tolerance": config.validation.reconciliation_tolerance,
            "contract_mode": config.validation.contract_mode,
        },
        created_by=caller.identity,
    )
    session.add(ingestion_config)
    session.flush()

    # Auto-create the pipeline (FR-002 "no custom code").
    pipeline = IngestionPipeline(
        config_id=ingestion_config.id,
        source_id=source.id,
        name=_pipeline_name(source.name, config.metadata.name),
        schedule=config.schedule,
        owner_identity=caller.identity,
    )
    session.add(pipeline)
    session.flush()

    audit = AuditService(session)
    if is_new:
        audit.config_created(
            actor=caller.identity,
            platform_id=source.platform_id,
            source_id=source.id,
            config_id=ingestion_config.id,
            version=version,
            config_hash=ingestion_config.config_hash,
        )
    else:
        audit.config_updated(
            actor=caller.identity,
            platform_id=source.platform_id,
            source_id=source.id,
            config_id=ingestion_config.id,
            version=version,
            config_hash=ingestion_config.config_hash,
        )
    session.flush()
    return ConfigCreated(
        config_id=ingestion_config.id,
        version=version,
        pipeline_id=pipeline.id,
    )


@router.get("/sources/{source_id}/config", response_model=ConfigExport)
def export_ingestion_config(
    source_id: uuid.UUID,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
) -> ConfigExport:
    """Export the latest ingestion config (FR-017); no plaintext secrets (SC-007)."""
    _get_source(session, source_id)
    config = session.execute(
        select(IngestionConfig)
        .where(IngestionConfig.source_id == source_id)
        .order_by(IngestionConfig.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    if config is None:
        raise NotFoundError(f"no ingestion config for source {source_id}")
    return ConfigExport(
        version=config.version,
        config_yaml=config.config_yaml,
        config_hash=f"sha256:{config.config_hash}",
    )


def _selected_objects(config) -> dict[str, Any]:
    """Normalise selected objects into the model's JSON shape."""
    objects = []
    for obj in config.source.objects or []:
        objects.append(
            {
                "name": obj.name,
                "mode": obj.mode,
                "cursor_column": obj.cursor_column,
            }
        )
    return {"objects": objects}


def _ingestion_mode(config) -> IngestionMode:
    modes = {obj.mode for obj in config.source.objects or []}
    return IngestionMode.incremental if "incremental" in modes else IngestionMode.full


def _error_path(msg: str) -> str:
    return msg.split(":", 1)[0] if ":" in msg else "$"
