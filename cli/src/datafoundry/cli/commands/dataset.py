"""``datafoundry dataset register/list/status`` (T020, quickstart Scenario 1).

- ``dataset register <platform_id> --name <name> --layer <layer> --schema <path>
  --owner <email> --classification <class>`` — register a dataset
  (POST /datasets).
- ``dataset list`` — list datasets (GET /datasets).
- ``dataset status <dataset_id>`` — dataset detail with promotion state
  (GET /datasets/{id}).
"""

from __future__ import annotations

import json

import typer
from datafoundry.cli.client import ApiClient, console, error_console
from rich.table import Table

app = typer.Typer(help="Datasets: register, list, and inspect Medallion datasets.")


@app.command("register")
def dataset_register(
    platform_id: str = typer.Argument(..., help="Owning platform id"),
    name: str = typer.Option(..., "--name", help="Dataset name"),
    layer: str = typer.Option(..., "--layer", help="bronze | silver | gold"),
    schema: str = typer.Option(..., "--schema", help="Path to schema JSON"),
    owner: str = typer.Option(..., "--owner", help="Owner identity"),
    classification: str = typer.Option("internal", "--classification"),
    steward: str = typer.Option(None, "--steward", help="Steward identity"),
    domain: str = typer.Option(None, "--domain", help="Business domain"),
    description: str = typer.Option(None, "--description", help="Description"),
    quality_score: float = typer.Option(None, "--quality-score", help="Quality score 0-100 (Gold)"),
    refresh: str = typer.Option(
        None, "--refresh", help='Refresh metadata JSON, e.g. \'{"schedule":"daily"}\''
    ),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Register a dataset (FR-014)."""
    with open(schema) as handle:
        schema_definition = json.load(handle)
    body = {
        "platform_id": platform_id,
        "name": name,
        "layer": layer,
        "schema_definition": schema_definition,
        "owner_identity": owner,
        "classification": classification,
        "steward_identity": steward,
        "domain": domain,
        "description": description,
        "quality_score": quality_score,
        "refresh_metadata": json.loads(refresh) if refresh else None,
    }
    with ApiClient(base_url=api_url) as client:
        response = client.post("/datasets", json_body=body)
    if response.status_code == 201:
        dataset_id = response.json()["dataset_id"]
        console.print(f"[green]✓ dataset registered[/green] dataset_id={dataset_id}")
        raise typer.Exit(code=0)
    if response.status_code == 422:
        _print_errors(response)
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("list")
def dataset_list(
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """List datasets (FR-013)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get("/datasets")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    items = response.json()["items"]
    table = Table(title="Datasets")
    table.add_column("dataset_id")
    table.add_column("name")
    table.add_column("layer")
    table.add_column("owner")
    table.add_column("classification")
    table.add_column("promotion_state")
    for item in items:
        table.add_row(
            item["dataset_id"],
            item["name"],
            item["layer"],
            item["owner"],
            item["classification"],
            item.get("promotion_state") or "",
        )
    console.print(table)
    raise typer.Exit(code=0)


@app.command("status")
def dataset_status(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Dataset detail with promotion state (US4-AC3)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/datasets/{dataset_id}")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(f"[green]{data['name']}[/green] layer={data['layer']}")
    console.print(f"  owner={data['owner']} classification={data['classification']}")
    console.print(f"  promotion_state={data.get('promotion_state') or 'unregistered'}")
    if data.get("blocked_reason"):
        console.print(f"  [red]blocked: {data['blocked_reason']}[/red]")
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
