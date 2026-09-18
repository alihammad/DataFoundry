"""``datafoundry transform define/run/history`` (T027, quickstart Scenario 2).

- ``transform define --config <path>`` — define a transformation
  (POST /transformations).
- ``transform run <transform_id> --input <dataset_id>`` — run a transformation
  (POST /transformations/{id}/run).
- ``transform history <transform_id>`` — run history
  (GET /transformations/{id}/runs).
"""

from __future__ import annotations

import json

import typer
from datafoundry.cli.client import ApiClient, console, error_console
from rich.table import Table

app = typer.Typer(help="Transformations: define, run, and inspect Medallion transforms.")


@app.command("define")
def transform_define(
    config: str = typer.Option(..., "--config", help="Path to transformation JSON"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Define a transformation (FR-005)."""
    with open(config) as handle:
        body = json.load(handle)
    with ApiClient(base_url=api_url) as client:
        response = client.post("/transformations", json_body=body)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ transformation defined[/green] "
            f"transformation_id={data['transformation_id']} version={data['version']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 422:
        _print_errors(response)
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("run")
def transform_run(
    transformation_id: str = typer.Argument(..., help="Transformation id"),
    input: str = typer.Option(..., "--input", help="Input dataset id"),
    environment: str = typer.Option("production", "--environment"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Run a transformation (FR-005, FR-017)."""
    body = {"input_dataset_id": input, "environment": environment}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/transformations/{transformation_id}/run", json_body=body)
    if response.status_code == 200:
        data = response.json()
        console.print(
            f"[green]✓ transformation run[/green] "
            f"output_dataset_id={data['output_dataset_id']} "
            f"output_version={data['output_version']}"
        )
        console.print(
            f"  record_count={data['record_count']} quarantined_count={data['quarantined_count']}"
        )
        console.print(f"  promotion_state={data['promotion_state']}")
        if data.get("gate_report_id"):
            console.print(f"  gate_report_id={data['gate_report_id']}")
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("history")
def transform_history(
    transformation_id: str = typer.Argument(..., help="Transformation id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Run history for a transformation (FR-017)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/transformations/{transformation_id}/runs")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    items = response.json()["items"]
    table = Table(title="Transformation runs")
    table.add_column("run_id")
    table.add_column("input_version")
    table.add_column("output_version")
    table.add_column("record_count")
    table.add_column("quarantined_count")
    table.add_column("promotion_state")
    table.add_column("ran_at")
    for item in items:
        table.add_row(
            item["run_id"],
            str(item.get("input_version") or ""),
            str(item["output_version"]),
            str(item["record_count"]),
            str(item["quarantined_count"]),
            item.get("promotion_state") or "",
            item["ran_at"],
        )
    console.print(table)
    raise typer.Exit(code=0)


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
