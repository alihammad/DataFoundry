"""``datafoundry pipeline pause/resume/retry`` (T043, quickstart Scenario 6).

- ``pipeline list`` — list pipelines (GET /pipelines).
- ``pipeline pause <pipeline_id>`` — pause the schedule (POST /pipelines/{id}/pause).
- ``pipeline resume <pipeline_id>`` — resume the schedule (POST /pipelines/{id}/resume).
- ``pipeline retry <run_id>`` — retry a failed run (POST /runs/{id}/retry).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console
from rich.table import Table

app = typer.Typer(help="Ingestion pipelines: list, pause, resume, retry.")


@app.command("list")
def pipeline_list(
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """List ingestion pipelines (FR-013)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get("/pipelines")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    items = response.json()["items"]
    table = Table(title="Pipelines")
    table.add_column("pipeline_id")
    table.add_column("name")
    table.add_column("state")
    table.add_column("schedule")
    table.add_column("source")
    table.add_column("last_run_status")
    for item in items:
        table.add_row(
            item["pipeline_id"],
            item["name"],
            item["state"],
            item.get("schedule") or "",
            item["source"],
            item.get("last_run_status") or "",
        )
    console.print(table)
    raise typer.Exit(code=0)


@app.command("pause")
def pipeline_pause(
    pipeline_id: str = typer.Argument(..., help="Pipeline id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Pause the pipeline schedule (FR-014, US4-AC3)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/pipelines/{pipeline_id}/pause")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    console.print(f"[green]✓ pipeline paused[/green] state={response.json()['state']}")
    raise typer.Exit(code=0)


@app.command("resume")
def pipeline_resume(
    pipeline_id: str = typer.Argument(..., help="Pipeline id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Resume the pipeline schedule (FR-014)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/pipelines/{pipeline_id}/resume")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    console.print(f"[green]✓ pipeline resumed[/green] state={response.json()['state']}")
    raise typer.Exit(code=0)


@app.command("retry")
def pipeline_retry(
    run_id: str = typer.Argument(..., help="Failed run id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Retry a failed run (FR-014, US4-AC2)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/runs/{run_id}/retry")
    if response.status_code == 202:
        data = response.json()
        console.print(
            f"[green]✓ retry triggered[/green] run_id={data['run_id']} retry_of={data['retry_of']}"
        )
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)
