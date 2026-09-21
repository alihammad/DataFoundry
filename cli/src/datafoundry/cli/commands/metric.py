"""``datafoundry metric query/describe`` (T020, quickstart Scenario 1).

- ``metric query <metric_id> [--dimensions] [--filters]``
  (POST /semantic/metrics/{id}/query).
- ``metric describe <metric_id>`` (GET /semantic/metrics/{id}).
"""

from __future__ import annotations

import json

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Metrics: query and describe business metrics.")


@app.command("query")
def metric_query(
    metric_id: str = typer.Argument(..., help="Metric id"),
    dimensions: str = typer.Option("", "--dimensions", help="Comma-separated dimensions"),
    filters: str = typer.Option("{}", "--filters", help="JSON filters"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Query a metric (FR-002)."""
    body = {
        "dimensions": [d.strip() for d in dimensions.split(",") if d.strip()],
        "filters": json.loads(filters),
    }
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/semantic/metrics/{metric_id}/query", json_body=body)
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(f"value={data['value']}")
    console.print(f"  definition_version={data['definition_version']}")
    console.print(f"  dataset_versions={data['dataset_versions']}")
    console.print(f"  freshness={data['freshness']} quality_state={data['quality_state']}")
    raise typer.Exit(code=0)


@app.command("describe")
def metric_describe(
    metric_id: str = typer.Argument(..., help="Metric id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Describe a metric (US1-AC3, FR-006)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/semantic/metrics/{metric_id}")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    console.print(json.dumps(response.json(), indent=2))
    raise typer.Exit(code=0)


@app.command("deprecate")
def metric_deprecate(
    metric_id: str = typer.Argument(..., help="Metric id"),
    successor: str = typer.Option(None, "--successor", help="Successor metric id"),
    period: int = typer.Option(30, "--period", help="Availability period in days"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Deprecate a metric with an optional successor (FR-010)."""
    body = {
        "successor_metric_id": successor,
        "availability_period_days": period,
    }
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/semantic/metrics/{metric_id}/deprecate", json_body=body)
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(
        f"[green]✓ deprecated[/green] metric_id={data['metric_id']} "
        f"successor={data['successor_metric_id']} period={data['availability_period_days']}"
    )
    raise typer.Exit(code=0)
