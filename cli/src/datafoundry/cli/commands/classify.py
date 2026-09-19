"""``datafoundry classify set/get`` (T022, quickstart Scenario 1).

- ``classify set <dataset_id> --level <level> [--column <col>] [--policy <id>]``
  — set a dataset/column classification (POST /datasets/{id}/classification).
- ``classify get <dataset_id>`` — classification + protection metadata
  (GET /datasets/{id}/classification).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console
from rich.table import Table

app = typer.Typer(help="Classification: set and inspect dataset sensitivity levels.")


@app.command("set")
def classify_set(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    level: str = typer.Option(
        ..., "--level", help="public|internal|confidential|restricted|highly_restricted"
    ),
    column: str = typer.Option(None, "--column", help="Column name (dataset-level if omitted)"),
    policy: str = typer.Option(None, "--policy", help="Protection policy id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Set a dataset/column classification (FR-001)."""
    body = {"level": level, "column": column, "policy_id": policy}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/datasets/{dataset_id}/classification", json_body=body)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ classified[/green] classification_id={data['classification_id']} "
            f"level={data['level']}"
        )
        raise typer.Exit(code=0)
    if response.status_code in (422, 403):
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("get")
def classify_get(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Classification + protection metadata (FR-017)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/datasets/{dataset_id}/classification")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(f"dataset_id={data['dataset_id']} level={data['level']}")
    if data.get("columns"):
        table = Table(title="Column protection")
        table.add_column("column")
        table.add_column("mechanism")
        table.add_column("masking_status")
        table.add_column("authorised_roles")
        table.add_column("key_ref_id")
        for col in data["columns"]:
            table.add_row(
                col["column"],
                col["mechanism"],
                col.get("masking_status") or "",
                ", ".join(col.get("authorised_roles") or []),
                col.get("key_ref_id") or "",
            )
        console.print(table)
    raise typer.Exit(code=0)
