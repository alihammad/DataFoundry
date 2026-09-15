"""``datafoundry contract register/infer/approve`` (T026, quickstart Scenario 2).

- ``contract register <dataset_id> --schema <path>`` — register an explicit
  contract (POST /datasets/{id}/contracts/register).
- ``contract infer <dataset_id> --schema <path>`` — infer a contract from the
  observed schema (POST /datasets/{id}/contracts/infer).
- ``contract approve <contract_id> [--reject]`` — approve/reject an inferred
  contract (POST /contracts/{id}/approve).
"""

from __future__ import annotations

import json

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Data contracts: register, infer, and approve.")


def _load_schema(path: str) -> dict:
    """Load a contract schema JSON file (exit 2 on unreadable/invalid)."""
    try:
        with open(path) as handle:
            data = json.load(handle)
    except OSError as exc:
        error_console.print(f"[red]cannot read schema:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    except json.JSONDecodeError as exc:
        error_console.print(f"[red]invalid JSON:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    if not isinstance(data, dict):
        error_console.print("[red]schema must be a JSON object[/red]")
        raise typer.Exit(code=2)
    return data


@app.command("register")
def contract_register(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    schema: str = typer.Option(..., "--schema", "-s", help="Path to contract schema JSON"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Register an explicit contract (approved immediately, FR-006)."""
    schema_definition = _load_schema(schema)
    with ApiClient(base_url=api_url) as client:
        response = client.post(
            f"/datasets/{dataset_id}/contracts/register",
            json_body={"schema_definition": schema_definition},
        )
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ contract registered[/green] contract_id={data['contract_id']} "
            f"version={data['version']} origin={data['origin']} "
            f"approval_status={data['approval_status']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 422:
        _print_errors(response)
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("infer")
def contract_infer(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    schema: str = typer.Option(..., "--schema", "-s", help="Path to observed schema JSON"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Infer a contract from the observed schema (pending, FR-007)."""
    schema_definition = _load_schema(schema)
    with ApiClient(base_url=api_url) as client:
        response = client.post(
            f"/datasets/{dataset_id}/contracts/infer",
            json_body={"schema_definition": schema_definition},
        )
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ contract inferred[/green] contract_id={data['contract_id']} "
            f"version={data['version']} origin={data['origin']} "
            f"approval_status={data['approval_status']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 422:
        _print_errors(response)
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("approve")
def contract_approve(
    contract_id: str = typer.Argument(..., help="Contract id"),
    reject: bool = typer.Option(False, "--reject", help="Reject instead of approve"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Approve (or reject) an inferred contract (owner only, FR-007)."""
    body = {"action": "reject"} if reject else {}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/contracts/{contract_id}/approve", json_body=body)
    if response.status_code == 200:
        data = response.json()
        console.print(
            f"[green]✓ contract {data['approval_status']}[/green] contract_id={contract_id}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 403:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=3)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


def _print_errors(response) -> None:
    """Print all validation errors (SC-007)."""
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
        error_console.print(f"  [yellow]{error.get('path')}[/yellow]: {error.get('message')}")


if __name__ == "__main__":  # pragma: no cover
    app()
