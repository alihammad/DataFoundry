"""``datafoundry security-audit search/get`` (T043, quickstart Scenario 6).

- ``security-audit search [--identity] [--action]`` (GET /security-audit).
- ``security-audit get <audit_id>`` (GET /security-audit/{id}).
"""

from __future__ import annotations

import json

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Security audit: search and inspect tamper-evident records.")


@app.command("search")
def audit_search(
    identity: str = typer.Option(None, "--identity", help="Filter by identity"),
    action: str = typer.Option(None, "--action", help="Filter by action"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Search security audit records (FR-014)."""
    params = {}
    if identity:
        params["identity"] = identity
    if action:
        params["action"] = action
    with ApiClient(base_url=api_url) as client:
        response = client.get("/security-audit", **params)
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    items = response.json()["items"]
    if not items:
        console.print("No security audit records found.")
        raise typer.Exit(code=0)
    for item in items:
        console.print(
            f"{item['occurred_at']}  {item['identity']}  {item['action']}  "
            f"result={item['result']}  audit_id={item['audit_id']}"
        )
    raise typer.Exit(code=0)


@app.command("get")
def audit_get(
    audit_id: str = typer.Argument(..., help="Audit record id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Full record incl. hash chain for tamper verification (US6-AC1)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/security-audit/{audit_id}")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    console.print(json.dumps(response.json(), indent=2))
    raise typer.Exit(code=0)
