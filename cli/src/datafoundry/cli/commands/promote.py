"""``datafoundry promote status/override`` (T039, quickstart Scenario 4).

- ``promote status <dataset_id>`` — current promotion state + history
  (GET /datasets/{id}/promotion).
- ``promote override <dataset_id> --identity <email> --reason <text>
  --expiry <iso> --impact <text>`` — override a blocked gate
  (POST /datasets/{id}/promotion/override).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console
from rich.table import Table

app = typer.Typer(help="Promotion: inspect and override Medallion promotion states.")


@app.command("status")
def promote_status(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Current promotion state + history (US4-AC3)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/datasets/{dataset_id}/promotion")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(f"dataset_id={data['dataset_id']}")
    console.print(f"  current_state={data.get('current_state') or 'unregistered'}")
    history = data.get("history") or []
    if history:
        table = Table(title="Promotion history")
        table.add_column("state")
        table.add_column("gate_report_id")
        table.add_column("transitioned_at")
        table.add_column("blocked_reason")
        for item in history:
            table.add_row(
                item["state"],
                item.get("gate_report_id") or "",
                item.get("transitioned_at") or "",
                item.get("blocked_reason") or "",
            )
        console.print(table)
    raise typer.Exit(code=0)


@app.command("override")
def promote_override(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    identity: str = typer.Option(..., "--identity", help="Authorising identity"),
    reason: str = typer.Option(..., "--reason", help="Override reason"),
    expiry: str = typer.Option(..., "--expiry", help="Expiry ISO timestamp"),
    impact: str = typer.Option(..., "--impact", help="Impact assessment"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Override a blocked gate (FR-008)."""
    body = {
        "authorising_identity": identity,
        "reason": reason,
        "expiry": expiry,
        "impact_assessment": impact,
    }
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/datasets/{dataset_id}/promotion/override", json_body=body)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ override granted[/green] "
            f"override_id={data['override_id']} status={data['status']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 422:
        _print_errors(response)
        raise typer.Exit(code=1)
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
