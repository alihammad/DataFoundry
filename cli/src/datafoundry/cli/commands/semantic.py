"""``datafoundry semantic model set`` (T020, quickstart Scenario 1).

- ``semantic model set --config <path>`` — define a semantic model
  (POST /semantic/models).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console, load_config

app = typer.Typer(help="Semantic: define and manage semantic models.")


@app.command("model")
def semantic_model(
    config: str = typer.Option(..., "--config", help="Semantic model YAML path"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Define a semantic model (FR-001, FR-003)."""
    raw = load_config(config)
    with ApiClient(base_url=api_url) as client:
        response = client.post("/semantic/models", json_body=raw)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ model defined[/green] model_id={data['model_id']} "
            f"version={data['version']} certification_state={data['certification_state']}"
        )
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)
