"""``datafoundry protect apply/export`` (T022, quickstart Scenario 1).

- ``protect apply <dataset_id> --column <col>`` — apply protection to a column
  (via classification; POST /datasets/{id}/classification).
- ``protect export <dataset_id>`` — export protection metadata
  (GET /datasets/{id}/classification).
"""

from __future__ import annotations

import json

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Protection: apply and export column-level protection.")


@app.command("apply")
def protect_apply(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    column: str = typer.Option(..., "--column", help="Column to protect"),
    level: str = typer.Option("restricted", "--level", help="Classification level"),
    policy: str = typer.Option(None, "--policy", help="Protection policy id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Apply protection to a column (FR-002)."""
    body = {"level": level, "column": column, "policy_id": policy}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/datasets/{dataset_id}/classification", json_body=body)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ protected[/green] classification_id={data['classification_id']} "
            f"level={data['level']}"
        )
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("export")
def protect_export(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Export protection metadata (FR-017)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/datasets/{dataset_id}/classification")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    console.print(json.dumps(response.json(), indent=2))
    raise typer.Exit(code=0)
