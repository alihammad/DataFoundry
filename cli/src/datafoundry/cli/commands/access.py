"""``datafoundry access decide`` (T039, quickstart Scenario 5).

- ``access decide --identity <id> --resource <res> --action <act>``
  (POST /access/decide).
"""

from __future__ import annotations

import typer
from datafoundry.cli.client import ApiClient, console, error_console

app = typer.Typer(help="Access: evaluate the enforcement chain for a request.")


@app.command("decide")
def access_decide(
    identity: str = typer.Option(..., "--identity", help="Identity to evaluate"),
    resource: str = typer.Option(..., "--resource", help="dataset:<uuid>:column:<name>"),
    action: str = typer.Option("read", "--action", help="Action (read)"),
    api_url: str = typer.Option(None, "--api-url", help="Control-plane base URL"),
) -> None:
    """Evaluate the enforcement chain at query time (FR-013)."""
    body = {"identity": identity, "resource": resource, "action": action}
    with ApiClient(base_url=api_url) as client:
        response = client.post("/access/decide", json_body=body)
    if response.status_code != 200:
        error_console.print(ApiClient.problem_summary(response))
        raise typer.Exit(code=2)
    data = response.json()
    console.print(f"outcome={data['outcome']}")
    console.print(f"  classification_consulted={data['classification_consulted']}")
    if data.get("policy_applied"):
        console.print(f"  policy_applied={data['policy_applied']}")
    if data.get("reason"):
        console.print(f"  reason={data['reason']}")
    raise typer.Exit(code=0)
