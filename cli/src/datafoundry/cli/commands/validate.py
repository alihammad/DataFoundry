"""``datafoundry validate --config`` (T062).

POST /api/v1/validate — no side effects (SC-004). Exit 1 with ALL errors +
remediation on invalid configs (SC-007); exit 0 when valid.
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import (
    ApiClient,
    console,
    error_console,
    load_config,
    print_validation_errors,
)


def validate(
    config: str = typer.Option(..., "--config", "-c", help="Path to platform config YAML"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Validate a platform config without deploying (all errors at once)."""
    raw = load_config(config)
    with ApiClient(base_url=api_url) as client:
        response = client.post("/validate", json_body={"config": raw})
    if response.status_code == 200:
        console.print(f"[green]✓ config is valid:[/green] {config}")
        raise typer.Exit(code=0)
    if response.status_code == 422:
        print_validation_errors(response)
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)
