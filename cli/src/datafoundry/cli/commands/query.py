"""``datafoundry query run/download`` (T045, quickstart Scenario 5).

- ``query run <dataset_id> --sql <sql>`` — run a SQL query against a
  Silver/Gold dataset (POST /datasets/{id}/query).
- ``query download <dataset_id> --sql <sql> --format csv|parquet`` — download
  a result set with column-level protection (POST /datasets/{id}/query/download).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console
from rich.table import Table

app = typer.Typer(help="Query Silver/Gold datasets directly with SQL.")


@app.command("run")
def query_run(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    sql: str = typer.Option(..., "--sql", help="SQL query"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Run a SQL query against a dataset (FR-016)."""
    body = {"sql": sql}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/datasets/{dataset_id}/query", json_body=body)
    if response.status_code == 200:
        data = response.json()
        table = Table(title=f"Query result ({data['row_count']} rows)")
        for column in data["columns"]:
            table.add_column(column)
        for row in data["rows"]:
            table.add_row(*[str(v) for v in row])
        console.print(table)
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("download")
def query_download(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    sql: str = typer.Option(..., "--sql", help="SQL query"),
    format: str = typer.Option("csv", "--format", help="csv | parquet"),
    output: str = typer.Option(None, "--output", help="Output file path"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Download a result set with column-level protection (US5-AC3)."""
    body = {"sql": sql, "format": format}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/datasets/{dataset_id}/query/download", json_body=body)
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    path = output or f"query_result.{format}"
    with open(path, "wb") as handle:
        handle.write(response.content)
    console.print(f"[green]✓ downloaded[/green] {path}")
    raise typer.Exit(code=0)
