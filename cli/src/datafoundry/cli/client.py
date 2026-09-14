"""Shared CLI plumbing: API client, config loading, progress rendering."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx
import typer
import yaml
from rich.console import Console
from rich.table import Table

console = Console()
error_console = Console(stderr=True)

DEFAULT_API_URL = "http://localhost:8000"
API_PREFIX = "/api/v1"


class ApiClient:
    """Thin HTTP client for the control-plane API (RFC 9457 aware)."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        provider: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("DF_API_URL", DEFAULT_API_URL)).rstrip("/")
        headers = {"Accept": "application/json"}
        token = token or os.environ.get("DF_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        provider = provider or os.environ.get("DF_PROVIDER")
        if provider:
            headers["x-datafoundry-provider"] = provider
        self._client = httpx.Client(base_url=self.base_url, headers=headers, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- verbs ----------------------------------------------------------

    def get(self, path: str, **params: Any) -> httpx.Response:
        return self._client.get(f"{API_PREFIX}{path}", params=params or None)

    def post(
        self, path: str, json_body: dict | None = None, headers: dict | None = None
    ) -> httpx.Response:
        return self._client.post(f"{API_PREFIX}{path}", json=json_body, headers=headers)

    def delete(self, path: str, **params: Any) -> httpx.Response:
        return self._client.delete(f"{API_PREFIX}{path}", params=params or None)

    # -- problem+json handling -------------------------------------------

    @staticmethod
    def problem_summary(response: httpx.Response) -> str:
        """Human-readable summary of an RFC 9457 problem+json response."""
        try:
            problem = response.json()
        except ValueError:
            return f"HTTP {response.status_code}: {response.text[:200]}"
        lines = [f"{problem.get('title', 'Error')} (HTTP {response.status_code})"]
        if problem.get("detail"):
            lines.append(f"  {problem['detail']}")
        for error in problem.get("errors", []):
            lines.append(f"  [{error.get('code')}] {error.get('path')}: {error.get('message')}")
            if error.get("remediation"):
                lines.append(f"      fix: {error['remediation']}")
        if problem.get("missing"):
            lines.append(f"  missing permissions: {', '.join(problem['missing'])}")
        if problem.get("code") and not problem.get("errors"):
            lines.append(f"  code: {problem['code']}")
        return "\n".join(lines)


def load_config(path: str) -> dict[str, Any]:
    """Load a platform config YAML (exit 2 on unreadable/invalid YAML)."""
    try:
        with open(path) as handle:
            config = yaml.safe_load(handle)
    except OSError as exc:
        error_console.print(f"[red]cannot read config:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    except yaml.YAMLError as exc:
        error_console.print(f"[red]invalid YAML:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    if not isinstance(config, dict):
        error_console.print("[red]config must be a YAML mapping[/red]")
        raise typer.Exit(code=2)
    return config


def print_validation_errors(response: httpx.Response) -> None:
    """Print all errors + remediation (SC-007)."""
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
        error_console.print(
            f"  [yellow]{error.get('path')}[/yellow] [{error.get('code')}]: {error.get('message')}"
        )
        if error.get("remediation"):
            error_console.print(f"    [dim]fix: {error['remediation']}[/dim]")


def step_table(run: dict[str, Any]) -> Table:
    table = Table(title=f"Run {run['run_id']} — {run['status']}")
    table.add_column("#", justify="right")
    table.add_column("Step")
    table.add_column("Status")
    table.add_column("Detail")
    icons = {
        "succeeded": "[green]✓ succeeded[/green]",
        "failed": "[red]✗ failed[/red]",
        "running": "[yellow]▶ running[/yellow]",
        "pending": "[dim]… pending[/dim]",
        "skipped": "[dim]⊘ skipped[/dim]",
    }
    for step in run["steps"]:
        detail = step.get("error_detail") or step.get("detail") or ""
        table.add_row(
            str(step["position"]),
            step["key"],
            icons.get(step["status"], step["status"]),
            detail,
        )
    return table


def wait_for_run(
    client: ApiClient,
    run_id: str,
    *,
    poll_interval: float = 2.0,
    timeout: float = 1800.0,
) -> dict[str, Any]:
    """Poll GET /runs/{run_id} until terminal; stream ordered step progress."""
    deadline = time.monotonic() + timeout
    last_rendered = ""
    while True:
        response = client.get(f"/runs/{run_id}")
        if response.status_code != 200:
            error_console.print(ApiClient.problem_summary(response))
            raise typer.Exit(code=2)
        run = response.json()
        signature = (
            "".join(f"{s['position']}:{s['status']}:{s.get('attempt', 0)}" for s in run["steps"])
            + run["status"]
        )
        if signature != last_rendered:
            console.print(step_table(run))
            last_rendered = signature
        if run["status"] in ("succeeded", "failed", "rolled_back"):
            return run
        if time.monotonic() > deadline:
            error_console.print("[red]timed out waiting for run[/red]")
            raise typer.Exit(code=2)
        time.sleep(poll_interval)
