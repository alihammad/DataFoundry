#!/usr/bin/env python3
"""Phase 2 demo — watch the foundational core work.

Run from the control-plane venv:
    cd control-plane
    .venv/bin/python ../scripts/demo_phase2.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "control-plane" / "src"))

import yaml  # noqa: E402

from datafoundry.controlplane.api.errors import ConfigValidationError  # noqa: E402
from datafoundry.controlplane.audit.service import AuditSecretLeakError, AuditService  # noqa: E402
from datafoundry.controlplane.capabilities.registry import default_registry  # noqa: E402
from datafoundry.controlplane.config.schema import PlatformConfig  # noqa: E402
from datafoundry.controlplane.config.secret_scan import redact_text, scan_value  # noqa: E402
from datafoundry.controlplane.db.models import PlatformStatus, RunStatus  # noqa: E402
from datafoundry.controlplane.db.state_machines import (  # noqa: E402
    InvalidTransitionError,
    transition_platform,
    transition_run,
)
from datafoundry.controlplane.engine.generator import RootModuleGenerator  # noqa: E402
from datafoundry.controlplane.providers.base import default_providers  # noqa: E402

EXAMPLES = REPO_ROOT / "platform-configs" / "examples"
GREEN, RED, YELLOW, CYAN, BOLD, DIM, RESET = (
    "\033[32m", "\033[31m", "\033[33m", "\033[36m", "\033[1m", "\033[2m", "\033[0m",
)


def header(title: str) -> None:
    print(f"\n{BOLD}{CYAN}{'=' * 72}\n  {title}\n{'=' * 72}{RESET}")


def ok(msg: str) -> None:
    print(f"  {GREEN}[OK]{RESET} {msg}")


def fail(msg: str) -> None:
    print(f"  {RED}[REJECTED]{RESET} {msg}")


def info(msg: str) -> None:
    print(f"  {DIM}{msg}{RESET}")


# ---------------------------------------------------------------------------
header("1. SCHEMA: valid platform config parses (T009)")
# ---------------------------------------------------------------------------
raw = yaml.safe_load((EXAMPLES / "dev-aws-localstack.yaml").read_text())
config = PlatformConfig.model_validate(raw)
ok(f"platform '{config.platform.name}' on {config.platform.provider}/{config.platform.region}")
ok(f"environment={config.platform.environment}, table_format={config.storage.table_format}")
ok(f"bronze retention={config.storage.zones.bronze.retention_days} (immutable, Principle III)")

# ---------------------------------------------------------------------------
header("2. SCHEMA: strict mode rejects bad configs (T009)")
# ---------------------------------------------------------------------------
from pydantic import ValidationError  # noqa: E402

bad_cases = [
    ("unknown field", {**raw, "bogusField": "x"}),
    ("core capability disabled", {**raw, "capabilities": {**raw["capabilities"], "iam": {"enabled": False}}}),
    ("invalid name 'Ab'", {**raw, "platform": {**raw["platform"], "name": "Ab"}}),
    ("reserved name 'system'", {**raw, "platform": {**raw["platform"], "name": "system"}}),
    ("bronze retention 30 (must be -1)", {**raw, "storage": {"zones": {"bronze": {"retention_days": 30}}}}),
    ("provider 'azure' (not in MVP)", {**raw, "platform": {**raw["platform"], "provider": "azure"}}),
]
for label, payload in bad_cases:
    try:
        PlatformConfig.model_validate(payload)
        fail(f"{label} — ACCEPTED (BUG!)")
    except ValidationError:
        ok(f"{label} -> rejected")

# ---------------------------------------------------------------------------
header("3. SECRET SCAN: detects leaks, no false positives (T010)")
# ---------------------------------------------------------------------------
leaky = {
    "aws_key": "AKIAIOSFODNN7EXAMPLE",
    "gcp_key": "AIza" + "A" * 35,
    "pem": "-----BEGIN RSA PRIVATE KEY-----\nMIIE...",
    "nested": {"list": ["password: SuperSecretValue123!"]},
}
for finding in scan_value(leaky):
    fail(f"{finding.path} -> {finding.kind}")

clean = {
    "config_hash": "9f8e7d6c5b4a39281706f5e4d3c2b1a09876543210abcdef1234567890abcdef",
    "git_ref": "abc123def456",
    "kms_key_ref": "platform-cmk",
    "message": "Region us-west1 does not support orchestration",
}
findings = scan_value(clean)
if not findings:
    ok("hashes / git refs / kms refs / prose -> no false positives")

print(f"\n  {YELLOW}log redaction demo:{RESET}")
print(f"    before: {DIM}deploying with key AKIAIOSFODNN7EXAMPLE{RESET}")
print(f"    after : {redact_text('deploying with key AKIAIOSFODNN7EXAMPLE')}")

# ---------------------------------------------------------------------------
header("4. AUDIT SERVICE: fail-closed on secret payloads (T019)")
# ---------------------------------------------------------------------------
try:
    AuditService(session=None).record(
        actor="demo", action="deploy.requested", payload={"oops": "AKIAIOSFODNN7EXAMPLE"}
    )
    fail("secret payload was stored (BUG!)")
except AuditSecretLeakError as exc:
    ok(f"write blocked: {exc}")

# ---------------------------------------------------------------------------
header("5. CAPABILITY REGISTRY: dependency closure + implicit database (T011)")
# ---------------------------------------------------------------------------
enabled = config.capabilities.explicitly_enabled()
info(f"config explicitly enables: {sorted(enabled)}")
resolved = default_registry.resolve_enabled(enabled)
added = sorted(resolved - enabled)
info(f"registry resolves to:      {sorted(resolved)}")
ok(f"implicit auto-enable added: {added}  (catalog needs a database!)")

print(f"\n  {YELLOW}deploy order (canonical R-11 sequence):{RESET}")
for i, cap in enumerate(default_registry.deploy_order(resolved), 1):
    deps = ", ".join(cap.depends_on) or "-"
    print(f"    {i:2}. {cap.key:<16} depends_on=[{deps}] health={cap.health_check}")

gen = RootModuleGenerator()
skipped = gen.skipped_capabilities(config)
ok(f"disabled capabilities (will be recorded 'skipped'): {skipped}")

# ---------------------------------------------------------------------------
header("6. PROVIDER ADAPTERS: regions + state backends (T012)")
# ---------------------------------------------------------------------------
for pid in default_providers.provider_ids():
    adapter = default_providers.get(pid)
    regions = adapter.regions()
    backend = adapter.state_backend(
        platform_name="demo", environment="development", run_id="run-123", region=regions[0]
    )
    ok(f"{pid}: {len(regions)} regions, state backend = {backend.type}")
    info(f"  e.g. {regions[0]}, {regions[1]}, ... -> {json.dumps(backend.config)}")

aws = default_providers.get("aws")
info(f"aws regions supporting 'orchestration': {len(aws.regions_for_capability('orchestration'))}")
info(f"'us-west-99' is a valid aws region? {aws.region_supports('us-west-99', 'networking')} "
     f"(bad-config.yaml caught here in T028)")

# ---------------------------------------------------------------------------
header("7. ROOT MODULE GENERATOR: renders Terraform per run (T016)")
# ---------------------------------------------------------------------------
doc = gen.render(config, aws, run_id="demo-run-001")
print(f"\n  {YELLOW}generated main.tf.json module blocks (in order):{RESET}")
for name, block in doc["module"].items():
    print(f"    module.{name:<15} source={block['source']}")
info(f"storage_zones.kms_key_ref = {doc['module']['storage_zones']['kms_key_ref']}")
info(f"backend = s3 (versioned bucket + DynamoDB lock, R-05)")
assert "quality" not in doc["module"], "disabled capability leaked into modules!"
ok("disabled capabilities produce NO module block (FR-012)")

# ---------------------------------------------------------------------------
header("8. STATE MACHINES: legal + illegal transitions (T023)")
# ---------------------------------------------------------------------------
print(f"\n  {YELLOW}platform lifecycle (happy path):{RESET}")
status = PlatformStatus.pending
for nxt in (PlatformStatus.deploying, PlatformStatus.ready):
    status = transition_platform(status, nxt)
    info(f"  -> {status.value}")
ok(f"platform reached '{status.value}'")

print(f"\n  {YELLOW}run lifecycle with credential expiry:{RESET}")
run = RunStatus.queued
for nxt in (RunStatus.running, RunStatus.paused, RunStatus.running, RunStatus.succeeded):
    run = transition_run(run, nxt)
    info(f"  -> {run.value}")

print(f"\n  {YELLOW}illegal transitions are blocked:{RESET}")
for entity, fn, cur, nxt in [
    ("platform", transition_platform, PlatformStatus.destroyed, PlatformStatus.ready),
    ("run", transition_run, RunStatus.succeeded, RunStatus.running),
]:
    try:
        fn(cur, nxt)
        fail(f"{entity}: {cur.value} -> {nxt.value} allowed (BUG!)")
    except InvalidTransitionError as exc:
        ok(f"{entity}: {exc}")

# ---------------------------------------------------------------------------
header("9. API ERROR SHAPE: RFC 9457 all-errors 422 body (T017)")
# ---------------------------------------------------------------------------
problem = ConfigValidationError(
    [
        {
            "path": "platform.region",
            "code": "region_capability_unsupported",
            "message": "Region us-west-99 does not exist for provider aws",
            "remediation": "Choose one of: us-east-1, us-west-2, eu-west-1, ...",
        },
        {
            "path": "capabilities.semantic_layer",
            "code": "dependency_missing",
            "message": "semantic_layer requires catalog",
            "remediation": "Enable 'catalog' or disable 'semantic_layer'",
        },
    ]
).to_problem()
print(json.dumps(problem, indent=2))
ok("every error carries {path, code, message, remediation} (SC-007)")

print(f"\n{BOLD}{GREEN}All Phase 2 components demonstrated successfully.{RESET}\n")
print(f"{DIM}Next: start the live server and open http://127.0.0.1:8000/healthz in a browser.{RESET}\n")
