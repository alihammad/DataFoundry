"""API router: query (T044, contracts/processing-api.md §5).

- ``POST /datasets/{id}/query`` — run a SQL query against Silver/Gold
  (FR-016): 200 columns/rows/row_count; 403 unauthorised (US5-AC2).
- ``POST /datasets/{id}/query/download`` — CSV/Parquet download with
  column-level protection applied (FR-016, US5-AC3).
"""

from __future__ import annotations

import io
import uuid
from typing import Any

from datafoundry.controlplane.api.auth import Caller, get_caller
from datafoundry.controlplane.api.deps import get_db, get_processing_gateway
from datafoundry.controlplane.api.errors import ForbiddenError, NotFoundError
from datafoundry.controlplane.db.models import Dataset
from datafoundry.controlplane.processing.query import apply_protection, run_query
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

router = APIRouter(tags=["query"])


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str


class QueryResponse(BaseModel):
    columns: list[str]
    rows: list[list[Any]]
    row_count: int


class DownloadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sql: str
    format: str = "csv"  # csv | parquet


def _get_dataset(session: Session, dataset_id: uuid.UUID) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if dataset is None:
        raise NotFoundError(f"no dataset with id {dataset_id}")
    return dataset


def _authorise(dataset: Dataset, caller: Caller) -> None:
    """Authorise the caller for the dataset (US5-AC2).

    MVP: the dataset owner (or the dev identity) may query. Unauthorised
    callers get 403.
    """
    if caller.identity != dataset.owner_identity:
        raise ForbiddenError(
            ["dataset.query"],
            detail=f"caller not authorised for dataset {dataset.name}",
        )


@router.post("/datasets/{dataset_id}/query", response_model=QueryResponse)
def query_dataset(
    dataset_id: uuid.UUID,
    body: QueryRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    processing_gateway: Any = Depends(get_processing_gateway),
) -> QueryResponse:
    """Run a SQL query against a Silver/Gold dataset (FR-016)."""
    dataset = _get_dataset(session, dataset_id)
    _authorise(dataset, caller)
    result = run_query(
        gateway=processing_gateway,
        dataset_id=str(dataset.id),
        layer=dataset.layer.value,
        sql=body.sql,
    )
    return QueryResponse(**result)


@router.post("/datasets/{dataset_id}/query/download")
def download_query(
    dataset_id: uuid.UUID,
    body: DownloadRequest,
    caller: Caller = Depends(get_caller),
    session: Session = Depends(get_db),
    processing_gateway: Any = Depends(get_processing_gateway),
) -> Response:
    """Download a result set with column-level protection (FR-016, US5-AC3)."""
    dataset = _get_dataset(session, dataset_id)
    _authorise(dataset, caller)
    table = processing_gateway.read_table(str(dataset.id), dataset.layer.value)
    protected = apply_protection(
        gateway=processing_gateway, dataset_id=str(dataset.id), table=table
    )

    if body.format == "parquet":
        buf = io.BytesIO()
        import pyarrow.parquet as pa_parquet

        pa_parquet.write_table(protected, buf)
        return Response(
            content=buf.getvalue(),
            media_type="application/vnd.apache.parquet",
            headers={"Content-Disposition": f'attachment; filename="{dataset.name}.parquet"'},
        )

    # Default CSV.
    buf = io.BytesIO()
    import pyarrow.csv as pa_csv

    pa_csv.write_csv(protected, buf)
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{dataset.name}.csv"'},
    )
