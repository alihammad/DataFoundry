"""``datafoundry export --platform <name|id>`` (T075).

GET /api/v1/platforms/{id}/config and write the secret-free YAML to stdout
(FR-011, US2-AC1). Exit 0 on success; the output is a valid PlatformConfig
document ready to re-deploy (SC-002).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console


def _find_platform_id(client: ApiClient, name_or_id: str) -> str:
    cursor: str | None = None
    while True:
        params: dict = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        response = client.get("/platforms", **params)
        if response.status_code != 200:
            error_console.print(ApiClient.problem_summary(response))
            raise typer.Exit(code=2)
        body = response.json()
        for item in body["items"]:
            if name_or_id in (item["name"], item["id"]):
                return item["id"]
        cursor = body.get("next_cursor")
        if not cursor:
            error_console.print(f"[red]platform not found:[/red] {name_or_id}")
            raise typer.Exit(code=1)


def export(
    platform: str = typer.Option(..., "--platform", "-p", help="Platform name or id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Export a platform's config as secret-free YAML to stdout (FR-011)."""
    with ApiClient(base_url=api_url) as client:
        platform_id = _find_platform_id(client, platform)
        response = client.get(f"/platforms/{platform_id}/config")
        if response.status_code != 200:
            error_console.print(ApiClient.problem_summary(response))
            raise typer.Exit(code=2)
        data = response.json()

    console.print(data["config_yaml"], end="")
    # Provenance goes to stderr so stdout stays a clean YAML document.
    error_console.print(
        f"[dim]# version={data['version']} config_hash={data['config_hash']} "
        f"git_ref={data.get('git_ref') or '-'}[/dim]"
    )
    raise typer.Exit(code=0)
