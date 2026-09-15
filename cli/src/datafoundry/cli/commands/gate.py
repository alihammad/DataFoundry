"""``datafoundry gate set/run/report`` (T020, quickstart Scenario 1).

- ``gate set <dataset_id> <transition> --config <path>`` — define a gate
  (POST /datasets/{id}/gates/{transition}).
- ``gate run <gate_id> --run <run_id> --batch <batch_id> [--env]`` — run the
  gate against a batch (POST /gates/{id}/run).
- ``gate report <gate_id> <report_id>`` — gate report detail with per-test
  results (GET /gates/{id}/reports/{report_id}).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console, load_config
from rich.table import Table

app = typer.Typer(help="Quality gates: define, run, and inspect gate reports.")


@app.command("set")
def gate_set(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    transition: str = typer.Argument(..., help="Layer transition (e.g. bronze_to_silver)"),
    config: str = typer.Option(..., "--config", "-c", help="Path to gate config YAML"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Define a quality gate on a layer transition (FR-001, FR-018)."""
    raw = load_config(config)
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/datasets/{dataset_id}/gates/{transition}", json_body=raw)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ gate defined[/green] gate_id={data['gate_id']} "
            f"config_version={data['config_version']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 422:
        _print_errors(response)
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("run")
def gate_run(
    gate_id: str = typer.Argument(..., help="Gate id"),
    run_id: str = typer.Option(..., "--run", help="Run id being gated"),
    batch_id: str = typer.Option(..., "--batch", help="Batch id"),
    env: str = typer.Option("production", "--env", help="Environment (severity override)"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Run the gate against a batch (FR-001, FR-013)."""
    body = {"run_id": run_id, "batch_id": batch_id, "environment": env}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/gates/{gate_id}/run", json_body=body)
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    colour = "red" if data["decision"] == "block" else "green"
    console.print(
        f"[{colour}]decision: {data['decision']}[/{colour}] "
        f"overall: {data['overall_status']} "
        f"(run {data['tests_run']}, passed {data['tests_passed']}, "
        f"warned {data['tests_warned']}, failed {data['tests_failed']}) "
        f"config_version={data['config_version']}"
    )
    _render_results(data["results"])
    raise typer.Exit(code=0 if data["decision"] == "promote" else 1)


@app.command("report")
def gate_report(
    report_id: str = typer.Argument(..., help="Report id"),
    gate_id: str = typer.Option(None, "--gate", help="Gate id (optional)"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Show a gate report with per-test results (US1-AC3, FR-015).

    With ``--gate`` uses ``GET /gates/{gate_id}/reports/{report_id}``; without
    it uses the drill-down ``GET /reports/{report_id}`` (US6-AC2, FR-015).
    """
    with ApiClient(base_url=api_url) as client:
        if gate_id:
            response = client.get(f"/gates/{gate_id}/reports/{report_id}")
        else:
            response = client.get(f"/reports/{report_id}")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(
        f"report_id={data['report_id']} decision={data['decision']} "
        f"overall={data['overall_status']} config_version={data['config_version']}"
    )
    _render_results(data["results"])
    if data.get("quarantine_entries"):
        console.print("[bold]quarantine entries:[/bold]")
        for entry in data["quarantine_entries"]:
            console.print(
                f"  {entry['entry_id']} {entry['failure_reason']} "
                f"(failed_test={entry.get('failed_test') or 'n/a'})"
            )
    raise typer.Exit(code=0)


def _render_results(results: list[dict]) -> None:
    """Render per-test results as a table."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("test")
    table.add_column("category")
    table.add_column("severity")
    table.add_column("status")
    table.add_column("failed")
    for item in results:
        table.add_row(
            item.get("test", ""),
            item.get("category", ""),
            item.get("severity", ""),
            item.get("status", ""),
            str(item.get("failed_record_count", 0)),
        )
    console.print(table)


def _print_errors(response) -> None:
    """Print all validation errors (SC-007)."""
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
