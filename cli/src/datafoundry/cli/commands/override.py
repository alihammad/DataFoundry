"""``datafoundry override grant`` (T041, quickstart Scenario 4).

- ``override grant <report_id> --identity <id> --reason <text> --expiry <ts>
  --impact <text>`` — grant an override for a blocked run
  (POST /reports/{id}/override).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Overrides: grant a controlled bypass of a failed gate.")


@app.command("grant")
def override_grant(
    report_id: str = typer.Argument(..., help="Gate report id (blocked run)"),
    identity: str = typer.Option(..., "--identity", help="Authorising identity"),
    reason: str = typer.Option(..., "--reason", help="Reason for the override"),
    expiry: str = typer.Option(..., "--expiry", help="Expiry timestamp (ISO 8601)"),
    impact: str = typer.Option(..., "--impact", help="Impact assessment"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Grant an override for a blocked run (FR-011, FR-012)."""
    body = {
        "authorising_identity": identity,
        "reason": reason,
        "expiry": expiry,
        "impact_assessment": impact,
    }
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/reports/{report_id}/override", json_body=body)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ override granted[/green] override_id={data['override_id']} "
            f"status={data['status']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 422:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=1)
    if response.status_code == 403:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


if __name__ == "__main__":  # pragma: no cover
    app()