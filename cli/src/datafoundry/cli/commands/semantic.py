"""``datafoundry semantic model set/publish/approve`` + ``semantic test run``
(T020/T028, quickstart Scenarios 1-2).

- ``semantic model set --config <path>`` — define a semantic model
  (POST /semantic/models).
- ``semantic model publish <model_id> --classification <c>`` — propose a
  publication (POST /semantic/models/{id}/publish).
- ``semantic model approve <publication_id>`` — approve a publication
  (POST /publications/{id}/approve).
- ``semantic test run <test_id>`` — run a semantic test
  (POST /semantic/tests/{id}/run).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console, load_config

app = typer.Typer(help="Semantic: define, publish, and test semantic models.")
model_app = typer.Typer(help="Semantic model operations.")
test_app = typer.Typer(help="Semantic test operations.")
app.add_typer(model_app, name="model")
app.add_typer(test_app, name="test")


@model_app.command("set")
def semantic_model_set(
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


@model_app.command("publish")
def semantic_model_publish(
    model_id: str = typer.Argument(..., help="Semantic model id"),
    classification: str = typer.Option(
        "non_breaking", "--classification", help="breaking | non_breaking"
    ),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Propose a publication (FR-003, FR-004)."""
    body = {"change_classification": classification}
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/semantic/models/{model_id}/publish", json_body=body)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ publication proposed[/green] "
            f"publication_id={data['publication_id']} approval_status={data['approval_status']}"
        )
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@model_app.command("approve")
def semantic_model_approve(
    publication_id: str = typer.Argument(..., help="Publication id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Approve a publication (FR-005)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/publications/{publication_id}/approve", json_body={})
    if response.status_code == 200:
        data = response.json()
        console.print(
            f"[green]✓ approved[/green] approval_status={data['approval_status']} "
            f"published_at={data['published_at']}"
        )
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@test_app.command("run")
def semantic_test_run(
    test_id: str = typer.Argument(..., help="Semantic test id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Run a semantic test (FR-004, FR-014)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/semantic/tests/{test_id}/run", json_body={})
    if response.status_code == 200:
        data = response.json()
        console.print(
            f"[green]✓ test run[/green] status={data['status']} measured={data['measured_value']}"
        )
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)
