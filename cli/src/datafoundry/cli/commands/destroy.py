"""``datafoundry destroy --platform <name|id> [--wait]`` (T075).

DELETE /api/v1/platforms/{id} (production requires --approval-ref). The
destroy run tears down the platform in reverse order; with --wait, poll the
run until terminal.
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console, wait_for_run
from datafoundry.cli.commands.export import _find_platform_id


def destroy(
    platform: str = typer.Option(..., "--platform", "-p", help="Platform name or id"),
    wait: bool = typer.Option(False, "--wait", help="Poll until the destroy run is terminal"),
    approval_ref: str = typer.Option(
        None, "--approval-ref", help="Approval ticket ref (required for production, FR-010)"
    ),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Destroy a platform (reverse-order teardown, FR-009/FR-011)."""
    with ApiClient(base_url=api_url) as client:
        platform_id = _find_platform_id(client, platform)
        params = {"approval_ref": approval_ref} if approval_ref else None
        if params:
            response = client.delete(f"/platforms/{platform_id}", **params)
        else:
            response = client.delete(f"/platforms/{platform_id}")
        if response.status_code != 202:
            error_console.print(ApiClient.problem_summary(response))
            raise typer.Exit(code=2)
        accepted = response.json()
        console.print(
            f"[green]✓ destroy accepted[/green] run_id={accepted['run_id']} "
            f"run_type={accepted['run_type']}"
        )
        if not wait:
            raise typer.Exit(code=0)
        run = wait_for_run(client, accepted["run_id"])

    if run["status"] in ("rolled_back", "succeeded"):
        console.print("[green]✓ platform destroyed[/green]")
        raise typer.Exit(code=0)
    error_console.print(f"[red]destroy {run['status']}[/red]")
    raise typer.Exit(code=1)
