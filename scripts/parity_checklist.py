#!/usr/bin/env python3
"""Capability-parity checklist generator (T086, SC-003).

Produces the AWS-vs-GCP capability-parity checklist from the code-defined
capability registry + the *generated* module-availability matrix (never
hand-maintained — capability-catalog.md parity rule 2). The checklist is the
artifact used for the manual E2E gate (quickstart Scenario 6): a platform on
AWS and the same logical configuration on GCP must expose an identical set of
logical capabilities with zero platform-behaviour difference.

Usage (from the control-plane venv):
    python scripts/parity_checklist.py [--terraform-root terraform] [--out path]

Exit code 0 when parity holds (no gaps, every capability implemented on both
providers); non-zero when gaps exist so CI can gate on it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "control-plane" / "src"))

from datafoundry.controlplane.capabilities.registry import (  # noqa: E402
    Capability,
    default_registry,
)
from datafoundry.controlplane.providers.region_matrix import (  # noqa: E402
    available_modules,
    parity_report,
)

#: The four common outputs every capability module must implement (parity
#: guarantee — capability-catalog.md "Common module outputs"). Additional
#: provider-specific outputs are allowed but consumers rely only on these.
COMMON_OUTPUTS: tuple[str, ...] = (
    "endpoint",
    "resource_ids",
    "health_target",
    "iam_principal",
)


def _module_contract_ok(
    capability: Capability, terraform_root: Path, provider: str
) -> tuple[bool, str]:
    """Check a capability module implements the common input/output contract.

    Verifies the common inputs are declared in ``variables.tf`` and the common
    outputs in ``outputs.tf``. Returns ``(ok, detail)``.
    """
    module_dir = terraform_root / provider / (capability.module_dir or capability.key)
    variables = (
        (module_dir / "variables.tf").read_text() if (module_dir / "variables.tf").exists() else ""
    )
    outputs = (
        (module_dir / "outputs.tf").read_text() if (module_dir / "outputs.tf").exists() else ""
    )

    common_inputs = (
        "platform_name",
        "environment",
        "region",
        "kms_key_ref",
        "network_ref",
        "tags",
        "encryption_enforced",
    )
    missing_inputs = [name for name in common_inputs if f'variable "{name}"' not in variables]
    missing_outputs = [name for name in COMMON_OUTPUTS if f'output "{name}"' not in outputs]

    problems = []
    if missing_inputs:
        problems.append(f"missing inputs: {', '.join(missing_inputs)}")
    if missing_outputs:
        problems.append(f"missing outputs: {', '.join(missing_outputs)}")
    return (not problems, "; ".join(problems))


def build_checklist(terraform_root: Path) -> dict[str, Any]:
    """Build the parity checklist document.

    For every capability: which providers implement it (module exists on
    disk), whether each implementation conforms to the common input/output
    contract, and the health-check runner. The checklist is the SC-003
    evidence for AWS-vs-GCP parity.
    """
    registry = default_registry
    report = parity_report(terraform_root, registry=registry)
    providers = sorted(report["providers"])

    rows: list[dict[str, Any]] = []
    for key in sorted(registry.keys()):
        capability = registry.get(key)
        implemented: dict[str, bool] = {}
        contract: dict[str, str] = {}
        for provider in providers:
            exists = available_modules(provider, terraform_root, registry)[key]
            implemented[provider] = exists
            if exists:
                ok, detail = _module_contract_ok(capability, terraform_root, provider)
                contract[provider] = "ok" if ok else detail

        rows.append(
            {
                "capability": key,
                "display_name": capability.display_name,
                "selectable": capability.selectable,
                "depends_on": list(capability.depends_on),
                "health_check": capability.health_check,
                "implemented": implemented,
                "contract_conformance": contract,
            }
        )

    gaps = report["gaps"]
    parity_holds = all(not gap for gap in gaps.values()) and all(
        implemented[provider] for row in rows for provider in providers
    )

    return {
        "generated_from": str(terraform_root),
        "providers": providers,
        "capabilities": rows,
        "gaps": gaps,
        "parity_holds": parity_holds,
    }


def render_markdown(checklist: dict[str, Any]) -> str:
    """Render the checklist as a human-readable Markdown document."""
    lines = [
        "# Capability-Parity Checklist (SC-003)",
        "",
        f"Generated from: `{checklist['generated_from']}`",
        "",
        f"Providers compared: {', '.join(checklist['providers'])}",
        "",
        f"Parity holds: **{checklist['parity_holds']}**",
        "",
        "| Capability | Selectable | Health check | "
        + " | ".join(checklist["providers"])
        + " | Contract conformance |",
        "|---|---|---|" + "|---" * len(checklist["providers"]) + "|---|",
    ]
    for row in checklist["capabilities"]:
        impl = " | ".join(
            "✅" if row["implemented"].get(p) else "❌" for p in checklist["providers"]
        )
        conform = "; ".join(
            f"{p}: {row['contract_conformance'].get(p, 'n/a')}" for p in checklist["providers"]
        )
        lines.append(
            f"| {row['capability']} | {row['selectable']} | {row['health_check']} "
            f"| {impl} | {conform} |"
        )

    for provider, gap in checklist["gaps"].items():
        if gap:
            lines.append("")
            lines.append(f"**{provider} gaps**: {', '.join(gap)}")

    return "\n".join(lines) + "\n"


def quality_parity_check(repo_root: Path) -> dict[str, Any]:
    """Quality-engine cloud-independence check (feature 004, FR-019, SC-008).

    The quality engine must be cloud-independent: identical gate outcomes for
    identical data/config on both clouds. It must never talk to a cloud SDK
    directly — all reads go through the ``QualityGateway`` abstraction (S3/GCS
    adapters). This check scans the quality engine source for forbidden
    cloud-SDK imports (boto3, google.cloud) and confirms the engine routes
    reads through the gateway.
    """
    quality_dir = repo_root / "control-plane" / "src" / "datafoundry" / "controlplane" / "quality"
    forbidden = ("boto3", "google.cloud", "google.cloud.storage")
    violations: list[str] = []
    for path in sorted(quality_dir.rglob("*.py")):
        text = path.read_text()
        for token in forbidden:
            if token in text:
                violations.append(f"{path.relative_to(repo_root)}: imports {token}")

    # The engine must route reads through the gateway (not a cloud SDK).
    engine = quality_dir / "engine.py"
    uses_gateway = "gateway" in engine.read_text() if engine.exists() else False

    holds = not violations and uses_gateway
    return {
        "check": "quality_cloud_independence",
        "holds": holds,
        "forbidden_imports": violations,
        "engine_routes_through_gateway": uses_gateway,
    }


def render_quality_parity(check: dict[str, Any]) -> str:
    """Render the quality parity check as Markdown."""
    lines = [
        "# Quality Cloud-Independence Check (FR-019, SC-008)",
        "",
        f"Parity holds: **{check['holds']}**",
        "",
        f"Engine routes reads through gateway: **{check['engine_routes_through_gateway']}**",
    ]
    if check["forbidden_imports"]:
        lines.append("")
        lines.append("Forbidden cloud-SDK imports:")
        for v in check["forbidden_imports"]:
            lines.append(f"- {v}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capability-parity checklist generator (SC-003)")
    parser.add_argument(
        "--terraform-root",
        default=str(REPO_ROOT / "terraform"),
        help="Path to the terraform/ module tree (default: repo terraform/).",
    )
    parser.add_argument("--out", help="Write the Markdown checklist to this path.")
    parser.add_argument("--json", help="Write the raw JSON checklist to this path.")
    args = parser.parse_args(argv)

    terraform_root = Path(args.terraform_root)
    checklist = build_checklist(terraform_root)
    quality_check = quality_parity_check(REPO_ROOT)

    if args.json:
        Path(args.json).write_text(json.dumps(checklist, indent=2, sort_keys=True) + "\n")
    if args.out:
        Path(args.out).write_text(render_markdown(checklist))
    if not args.out and not args.json:
        print(render_markdown(checklist), end="")
        print()
        print(render_quality_parity(quality_check), end="")

    return 0 if checklist["parity_holds"] and quality_check["holds"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
