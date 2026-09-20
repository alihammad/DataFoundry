"""``datafoundry token tokenise/detokenise`` (T031, quickstart Scenario 3).

- ``token tokenise <dataset_id> --column <col> --value <v> [--deterministic]``
  (POST /datasets/{id}/tokens/tokenise).
- ``token detokenise <dataset_id> --column <col> --token <t> --purpose <p>``
  (POST /datasets/{id}/tokens/detokenise).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Tokens: tokenise and detokenise sensitive values.")


@app.command("tokenise")
def token_tokenise(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    column: str = typer.Option(..., "--column", help="Column to tokenise"),
    value: str = typer.Option(..., "--value", help="Value to tokenise"),
    deterministic: bool = typer.Option(True, "--deterministic/--random"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Tokenise a value (FR-011)."""
    body = {"column": column, "value": value, "deterministic": deterministic}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/datasets/{dataset_id}/tokens/tokenise", json_body=body)
    if response.status_code == 200:
        console.print(f"[green]✓ tokenised[/green] token={response.json()['token']}")
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("detokenise")
def token_detokenise(
    dataset_id: str = typer.Argument(..., help="Dataset id"),
    column: str = typer.Option(..., "--column", help="Column to detokenise"),
    token: str = typer.Option(..., "--token", help="Token to detokenise"),
    purpose: str = typer.Option(..., "--purpose", help="Approved purpose (FR-012)"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Detokenise (authorised only, FR-012)."""
    body = {"column": column, "token": token, "purpose": purpose}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/datasets/{dataset_id}/tokens/detokenise", json_body=body)
    if response.status_code == 200:
        console.print(f"[green]✓ detokenised[/green] value={response.json()['value']}")
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)
