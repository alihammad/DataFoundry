"""``datafoundry source configure`` and ``datafoundry ingest run`` (T024,
quickstart Scenarios 2-3).

- ``source configure <name|id> --config <path>`` — create/update an ingestion
  config (POST /sources/{id}/config); prints the auto-created pipeline_id.
- ``ingest run --pipeline <pipeline_id>`` — trigger a manual run
  (POST /pipelines/{id}/run).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console, load_config
from datafoundry.cli.commands.source import _find_source_id

app = typer.Typer(help="Ingestion: configure sources and trigger runs.")


@app.command("configure")
def source_configure(
    name_or_id: str = typer.Argument(..., help="Source name or id"),
    config: str = typer.Option(..., "--config", "-c", help="Path to ingestion config YAML"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Create/update an ingestion config; auto-creates the pipeline (FR-002)."""
    raw = load_config(config)
    with ApiClient(base_url=api_url) as client:
        source_id = _find_source_id(client, name_or_id)
        response = client.post(f"/sources/{source_id}/config", json_body=raw)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ config saved[/green] config_id={data['config_id']} "
            f"version={data['version']} pipeline_id={data['pipeline_id']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 422:
        _print_errors(response)
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("run")
def ingest_run(
    pipeline_id: str = typer.Option(..., "--pipeline", help="Pipeline id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Trigger a manual ingestion run (FR-011)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/pipelines/{pipeline_id}/run")
    if response.status_code == 202:
        data = response.json()
        console.print(
            f"[green]✓ run triggered[/green] run_id={data['run_id']} trigger={data['trigger']}"
        )
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


def _print_errors(response) -> None:
    try:
        problem = response.json()
    except ValueError:
        error_console.print(f"[red]HTTP {response.status_code}[/red]: {response.text}")
        return
    errors = problem.get("errors", [])
    error_console.print(
        f"[red]{problem.get('title', 'Validation failed')}[/red] "
        f"({len(errors)} error{'s' if len(errors) != 1 else ''})"
    )
    for error in errors:
        error_console.print(f"  [yellow]{error.get('path')}[/yellow]: {error.get('message')}")


if __name__ == "__main__":  # pragma: no cover
    app()
