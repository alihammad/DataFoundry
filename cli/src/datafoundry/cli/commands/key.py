"""``datafoundry key register/rotate/revoke/status`` (T027, quickstart Scenario 2).

- ``key register --kms <kms> --key-id <id>`` — register a key reference
  (POST /keys).
- ``key rotate <key_ref_id>`` — rotate to a new version (POST /keys/{id}/rotate).
- ``key revoke <key_ref_id>`` — revoke a key (POST /keys/{id}/revoke).
- ``key status <key_ref_id>`` — key reference status (GET /keys/{id}).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Keys: register, rotate, revoke, and inspect key references.")


@app.command("register")
def key_register(
    kms: str = typer.Option(..., "--kms", help="aws_kms | gcp_cloud_kms"),
    key_id: str = typer.Option(..., "--key-id", help="KMS key id (never material)"),
    version: int = typer.Option(1, "--version"),
    rotation_schedule: str = typer.Option(None, "--rotation-schedule"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Register a key reference (FR-008)."""
    body = {
        "kms": kms,
        "key_id": key_id,
        "version": version,
        "rotation_schedule": rotation_schedule,
        "usage_permissions": ["data-engineer"],
    }
    with ApiClient(base_url=api_url) as client:
        response = client.post("/keys", json_body=body)
    if response.status_code == 201:
        data = response.json()
        console.print(
            f"[green]✓ key registered[/green] key_ref_id={data['key_ref_id']} "
            f"version={data['version']}"
        )
        raise typer.Exit(code=0)
    if response.status_code == 422:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=1)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("rotate")
def key_rotate(
    key_ref_id: str = typer.Argument(..., help="Key reference id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Rotate to a new version (FR-009)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/keys/{key_ref_id}/rotate", json_body={})
    if response.status_code == 200:
        data = response.json()
        console.print(
            f"[green]✓ rotated[/green] version={data['version']} "
            f"lifecycle_state={data['lifecycle_state']}"
        )
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("revoke")
def key_revoke(
    key_ref_id: str = typer.Argument(..., help="Key reference id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Revoke a key (FR-008)."""
    with ApiClient(base_url=api_url) as client:
        response = client.post(f"/keys/{key_ref_id}/revoke", json_body={})
    if response.status_code == 200:
        data = response.json()
        console.print(f"[green]✓ revoked[/green] lifecycle_state={data['lifecycle_state']}")
        raise typer.Exit(code=0)
    error_console.print(ApiClient.problem_summary(response))
    raise typer.Exit(code=2)


@app.command("status")
def key_status(
    key_ref_id: str = typer.Argument(..., help="Key reference id"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Key reference status (never material, FR-008)."""
    with ApiClient(base_url=api_url) as client:
        response = client.get(f"/keys/{key_ref_id}")
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(f"key_ref_id={data['key_ref_id']}")
    console.print(f"  kms={data['kms']} key_id={data['key_id']}")
    console.print(f"  version={data['version']} lifecycle_state={data['lifecycle_state']}")
    if data.get("rotation_schedule"):
        console.print(f"  rotation_schedule={data['rotation_schedule']}")
    raise typer.Exit(code=0)
