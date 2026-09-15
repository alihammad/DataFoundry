"""``datafoundry quarantine list/replay`` (T032, quickstart Scenario 3).

- ``quarantine list <dataset_id> [--source] [--pipeline] [--batch] [--reason]
  [--date-from] [--date-to]`` — list + filter quarantine entries
  (GET /datasets/{id}/quarantine).
- ``quarantine replay <entry_id>`` — replay a quarantined record
  (POST /quarantine/{id}/replay).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console
from rich.table import Table

app = typer.Typer(help="Quarantine: list and replay rejected records.")


@app.command("list")
def quarantine_list(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    source: str = typer.Option(None, "--source", help="Filter by source"),
    pipeline: str = typer.Option(None, "--pipeline", help="Filter by pipeline id"),
    batch: str = typer.Option(None, "--batch", help="Filter by batch id"),
    reason: str = typer.Option(None, "--reason", help="Filter by failure reason (substring)"),
    date_from: str = typer.Option(None, "--date-from", help="Filter by quarantined_at >= date"),
    date_to: str = typer.Option(None, "--date-to", help="Filter by quarantined_at <= date"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """List quarantine entries for a dataset (US3-AC3)."""
    params = {
        "source": source,
        "pipeline_id": pipeline,
        "batch_id": batch,
        "failure_reason": reason,
        "date_from": date_from,
        "date_to": date_to,
    }
    params = {k: v for k, v in params.items() if v is not None}
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/datasets/{dataset_id}/quarantine", **params)
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    items = response.json()["items"]
    if not items:
        console.print("[yellow]no quarantine entries[/yellow]")
        raise typer.Exit(code=0)
    table = Table(show_header=True, header_style="bold")
    table.add_column("entry_id")
    table.add_column("batch_id")
    table.add_column("payload_ref")
    table.add_column("failure_reason")
    table.add_column("failed_test")
    table.add_column("attempts")
    table.add_column("eligible")
    for item in items:
        table.add_row(
            item["entry_id"],
            item["batch_id"],
            item["payload_ref"],
            item["failure_reason"],
            item.get("failed_test") or "",
            str(item["attempt_count"]),
            str(item["replay_eligible"]),
        )
    console.print(table)
    raise typer.Exit(code=0)


@app.command("replay")
def quarantine_replay(
    entry_id: str = typer.Argument(..., help="Quarantine entry id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Replay a quarantined record (FR-009, US3-AC2)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/quarantine/{entry_id}/replay")
    if response.status_code == 202:
        data = response.json()
        console.print(
            f"[green]✓ replayed[/green] entry_id={entry_id} replay_run_id={data['replay_run_id']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 409:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()
