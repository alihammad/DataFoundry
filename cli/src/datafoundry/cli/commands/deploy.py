"""``datafoundry deploy --config [--wait]`` (T063).

POST /api/v1/platforms (the "one click", FR-001); with --wait, streams
ordered step progress from GET /runs/{run_id} and surfaces failures with
error_detail (FR-008, US1-AC3).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import (
    ApiClient,
    console,
    error_console,
    load_config,
    print_validation_errors,
    wait_for_run,
)


def deploy(
    config: str = typer.Option(..., "--config", "-c", help="Path to platform config YAML"),
    wait: bool = typer.Option(False, "--wait", help="Stream step progress until terminal"),
    approval_ref: str = typer.Option(
        None, "--approval-ref", help="Approval ticket ref (required for production, FR-010)"
    ),
    idempotency_key: str = typer.Option(
        None, "--idempotency-key", help="Idempotency-Key header for safe retries"
    ),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Deploy a platform in one click (202 + run id; optional --wait)."""
    raw = load_config(config)
    body: dict = {"config": raw}
    if approval_ref:
        body["approval_ref"] = approval_ref
    headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None

    with ApiClient(base_url=api_url) as client:
        response = client.post("/platforms", json_body=body, headers=headers)
        if response.status_code == 422:
            print_validation_errors(response)
            raise typer.Exit(code=1)
        if response.status_code != 202:
            error_console.print(ApiClient.problem_summary(response))
            raise typer.Exit(code=2)
        accepted = response.json()
        console.print(
            f"[green]✓ deploy accepted[/green] platform_id={accepted['platform_id']} "
            f"run_id={accepted['run_id']} status={accepted['status']}"
        )
        if not wait:
            console.print(
                f"[dim]track progress: datafoundry status --run {accepted['run_id']}[/dim]"
            )
            raise typer.Exit(code=0)
        run = wait_for_run(client, accepted["run_id"])

    if run["status"] == "succeeded":
        console.print("[green]✓ platform deployed successfully[/green]")
        raise typer.Exit(code=0)
    error_console.print(f"[red]run {run['status']}[/red]")
    if run.get("failure"):
        error_console.print(f"  {run['failure']}")
    raise typer.Exit(code=1)
