"""``datafoundry status --platform <name|id>`` (T064).

Shows run progress, ordered step list and failure reasons (FR-008, US1-AC3).
Accepts ``--platform`` (resolves the latest run via GET /platforms) or a
direct ``--run`` id.
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import (
    ApiClient,
    console,
    error_console,
    step_table,
)


def _find_platform(client: ApiClient, name_or_id: str) -> dict | None:
    cursor: str | None = None
    while True:
        params: dict = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/platforms", **params)
        if response.status_code != 200:
            error_console.print(ApiClient.problem_summary(response))
            raise typer.Exit(code=2)
        body = response.json()
        for item in body["items"]:
            if name_or_id in (item["name"], item["id"]):
                return item
        cursor = body.get("next_cursor")
        if not cursor:
            return None


def _latest_run_id(client: ApiClient, platform_id: str) -> str | None:
    response = client.get(f"/platforms/{platform_id}/runs")
    if response.status_code != 200:
        return None
    items = response.json().get("items", [])
    return items[0]["run_id"] if items else None


def status(
    platform: str = typer.Option(None, "--platform", "-p", help="Platform name or id"),
    run: str = typer.Option(None, "--run", "-r", help="Run id (skips platform lookup)"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Show deployment run progress, step list and failure reasons."""
    if not platform and not run:
        error_console.print("[red]provide --platform or --run[/red]")
        raise typer.Exit(code=2)

    with ApiClient(base_url=api_url) as client:
        run_id = run
        if run_id is None:
            assert platform is not None
            item = _find_platform(client, platform)
            if item is None:
                error_console.print(f"[red]platform not found:[/red] {platform}")
                raise typer.Exit(code=1)
            console.print(
                f"platform [bold]{item['name']}[/bold] provider={item['provider']} "
                f"region={item['region']} env={item['environment_type']} "
                f"status=[bold]{item['status']}[/bold]"
            )
            run_id = _latest_run_id(client, item["id"])
            if run_id is None:
                console.print("[dim]no runs recorded for this platform[/dim]")
                raise typer.Exit(code=0)

        response = client.get(f"/runs/{run_id}")
        if response.status_code != 200:
            error_console.print(ApiClient.problem_summary(response))
            raise typer.Exit(code=2)
        data = response.json()

    console.print(step_table(data))
    if data.get("failure"):
        error_console.print(f"[red]failure:[/red] {data['failure']}")
        raise typer.Exit(code=1)
    if data["status"] == "failed":
        raise typer.Exit(code=1)
