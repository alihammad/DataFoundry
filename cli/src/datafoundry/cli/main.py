"""DataFoundry CLI entry point (T062).

``datafoundry`` typer app wiring the commands:
- ``validate --config <path>``        (T062)
- ``deploy --config <path> [--wait]`` (T063)
- ``status --platform <name|id>``     (T064)

Configuration via environment (see client.py): ``DF_API_URL``, ``DF_TOKEN``,
``DF_PROVIDER``.
"""

from __future__ import annotations

import sys

import typer
from datafoundry.cli.commands import deploy as deploy_cmd
from datafoundry.cli.commands import destroy as destroy_cmd
from datafoundry.cli.commands import export as export_cmd
from datafoundry.cli.commands import gate as gate_cmd
from datafoundry.cli.commands import status as status_cmd
from datafoundry.cli.commands import validate as validate_cmd

app = typer.Typer(
    name="datafoundry",
    help="DataFoundry: one-click governed lakehouse deployment.",
    add_completion=False,
    no_args_is_help=True,
)

app.command()(validate_cmd.validate)
app.command()(deploy_cmd.deploy)
app.command()(status_cmd.status)
app.command()(export_cmd.export)
app.command()(destroy_cmd.destroy)
app.add_typer(gate_cmd.app, name="gate")


def main() -> None:  # pragma: no cover - console entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
