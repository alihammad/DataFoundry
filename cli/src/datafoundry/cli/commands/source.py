"""``datafoundry source add/test/list`` (T023, quickstart Scenario 1).

- ``source add <name> --type <postgres|sqlserver|object_storage> ...`` — register
  a source (POST /sources).
- ``source test <name|id>`` — test connectivity (POST /sources/{id}/test).
- ``source list`` — list sources (GET /sources).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Data sources: register, test, and list ingestion sources.")


@app.command("add")
def source_add(
    name: str = typer.Argument(..., help="Source name (^[a-z][a-z0-9-]{2,62}$)"),
    type: str = typer.Option("postgres", "--type", help="postgres | sqlserver | object_storage"),
    platform_id: str = typer.Option(..., "--platform", help="Owning platform id"),
    host: str = typer.Option(None, "--host", help="Database host"),
    port: int = typer.Option(None, "--port", help="Database port"),
    database: str = typer.Option(None, "--database", help="Database name"),
    secret_ref: str = typer.Option(None, "--secret-ref", help="Secret manager key name"),
    location: str = typer.Option(None, "--location", help="Object-storage location (s3://...)"),
    fmt: str = typer.Option("parquet", "--format", help="Object-storage format"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Register a data source (FR-002)."""
    if type == "object_storage":
        config = {"location": location, "format": fmt}
    else:
        config = {
            "host": host,
            "port": port or (1433 if type == "sqlserver" else 5432),
            "database": database,
            "credentials": {"secretRef": secret_ref},
        }
    body = {
        "platform_id": platform_id,
        "name": name,
        "type": type,
        "config": config,
    }
    with ApiClient(base_url=api_url) as client:
        response = client.post("/sources", json_body=body)
    if response.status_code == 201:
        source_id = response.json()["source_id"]
        console.print(f"[green]✓ source registered[/green] source_id={source_id}")
        raise typer.Exit(code=0)
    if response.status_code == 422:
        _print_errors(response)
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("test")
def source_test(
    name_or_id: str = typer.Argument(..., help="Source name or id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Test connectivity (FR-004, US1-AC1/AC4)."""
    with ApiClient(base_url=api_url) as client:
        source_id = _find_source_id(client, name_or_id)
        response = client.post(f"/sources/{source_id}/test")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    if data["ok"]:
        console.print("[green]✓ ok: true[/green]")
        for obj in data.get("discovered_schema", []):
            cols = ", ".join(f"{c['name']}:{c['type']}" for c in obj["columns"])
            console.print(f"  {obj['object']} ({cols})")
        raise typer.Exit(code=0)
    console.print(f"[red]ok: false[/red] detail={data.get('detail')} message={data.get('message')}")
    raise typer.Exit(code=1)


@app.command("list")
def source_list(
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """List sources (FR-013)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get("/sources")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    items = response.json()["items"]
    for item in items:
        console.print(
            f"{item['source_id']}  {item['name']}  {item['type']}  state={item['connection_state']}"
        )
    raise typer.Exit(code=0)


def _find_source_id(client: ApiClient, name_or_id: str) -> str:
    """Resolve a source name to its id (or pass through an id)."""
    import uuid

    try:
        uuid.UUID(name_or_id)
        return name_or_id
    except ValueError:
        pass
    response = client.get("/sources")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    for item in response.json()["items"]:
        if item["name"] == name_or_id:
            return item["source_id"]
    error_console.print(f"[red]source '{name_or_id}' not found[/red]")
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
