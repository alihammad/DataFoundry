"""``datafoundry quality get/history`` (T046, quickstart Scenario 5).

- ``quality get <dataset_id>`` — current quality score + history
  (GET /datasets/{id}/quality).
- ``quality history <dataset_id>`` — per-run results for trend
  (GET /datasets/{id}/quality/history).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console
from rich.table import Table

app = typer.Typer(help="Quality: scores, history, and observability.")


@app.command("get")
def quality_get(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Show the current quality score + history (FR-014)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/datasets/{dataset_id}/quality")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(f"[bold]score: {data['score']}[/bold] (0-100)")
    _render_history(data["history"])
    raise typer.Exit(code=0)


@app.command("history")
def quality_history(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Show per-run results for trend (US6-AC1, FR-013)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/datasets/{dataset_id}/quality/history")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    _render_history(response.json()["items"])
    raise typer.Exit(code=0)


def _render_history(items: list[dict]) -> None:
    """Render per-run history as a table."""
    if not items:
        console.print("[yellow]no runs recorded[/yellow]")
        return
    table = Table(show_header=True, header_style="bold")
    table.add_column("report_id")
    table.add_column("decision")
    table.add_column("overall")
    table.add_column("run")
    table.add_column("passed")
    table.add_column("warned")
    table.add_column("failed")
    table.add_column("config")
    for item in items:
        table.add_row(
            item["report_id"],
            item["decision"],
            item["overall_status"],
            str(item["tests_run"]),
            str(item["tests_passed"]),
            str(item["tests_warned"]),
            str(item["tests_failed"]),
            str(item["config_version"]),
        )
    console.print(table)


if __name__ == "__main__":  # pragma: no cover
    app()
