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
from datafoundry.cli.commands import access as access_cmd
from datafoundry.cli.commands import classify as classify_cmd
from datafoundry.cli.commands import contract as contract_cmd
from datafoundry.cli.commands import dataset as dataset_cmd
from datafoundry.cli.commands import deploy as deploy_cmd
from datafoundry.cli.commands import destroy as destroy_cmd
from datafoundry.cli.commands import export as export_cmd
from datafoundry.cli.commands import gate as gate_cmd
from datafoundry.cli.commands import ingest as ingest_cmd
from datafoundry.cli.commands import key as key_cmd
from datafoundry.cli.commands import override as override_cmd
from datafoundry.cli.commands import pipeline as pipeline_cmd
from datafoundry.cli.commands import promote as promote_cmd
from datafoundry.cli.commands import protect as protect_cmd
from datafoundry.cli.commands import quality as quality_cmd
from datafoundry.cli.commands import quarantine as quarantine_cmd
from datafoundry.cli.commands import query as query_cmd
from datafoundry.cli.commands import security_audit as security_audit_cmd
from datafoundry.cli.commands import source as source_cmd
from datafoundry.cli.commands import status as status_cmd
from datafoundry.cli.commands import token as token_cmd
from datafoundry.cli.commands import transform as transform_cmd
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
app.add_typer(contract_cmd.app, name="contract")
app.add_typer(quarantine_cmd.app, name="quarantine")
app.add_typer(override_cmd.app, name="override")
app.add_typer(quality_cmd.app, name="quality")
app.add_typer(source_cmd.app, name="source")
app.add_typer(ingest_cmd.app, name="ingest")
app.add_typer(pipeline_cmd.app, name="pipeline")
app.add_typer(dataset_cmd.app, name="dataset")
app.add_typer(transform_cmd.app, name="transform")
app.add_typer(promote_cmd.app, name="promote")
app.add_typer(query_cmd.app, name="query")
app.add_typer(classify_cmd.app, name="classify")
app.add_typer(protect_cmd.app, name="protect")
app.add_typer(key_cmd.app, name="key")
app.add_typer(token_cmd.app, name="token")
app.add_typer(access_cmd.app, name="access")
app.add_typer(security_audit_cmd.app, name="security-audit")


def main() -> None:  # pragma: no cover - console entry point
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
