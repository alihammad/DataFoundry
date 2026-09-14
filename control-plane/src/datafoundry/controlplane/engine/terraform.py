"""Minimal Terraform CLI subprocess wrapper (T015, R-01).

``init``/``validate``/``plan``/``apply``/``destroy`` with ``-json`` streaming
parse, per-run workspace directory selection, and a pinned-binary version
check. Deliberately minimal — no terraform-exec dependency (R-01).
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from datafoundry.controlplane.config.settings import Settings, get_settings


class TerraformError(RuntimeError):
    """A terraform command failed. ``events`` holds parsed -json messages."""

    def __init__(self, command: str, returncode: int, stderr: str, events: list[dict[str, Any]]):
        self.command = command
        self.returncode = returncode
        self.stderr = stderr
        self.events = events
        summary = _summarise_errors(events) or stderr.strip() or f"exit code {returncode}"
        super().__init__(f"terraform {command} failed: {summary}")


class TerraformBinaryError(RuntimeError):
    """Terraform binary missing or below the pinned minimum version."""


@dataclass(frozen=True)
class TerraformEvent:
    """One parsed line of terraform -json output."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def hook_action(self) -> str | None:
        hook = self.payload.get("hook") or {}
        return hook.get("action")

    @property
    def resource(self) -> str | None:
        hook = self.payload.get("hook") or {}
        return (
            hook.get("resource", {}).get("addr") if isinstance(hook.get("resource"), dict) else None
        )


_VERSION_RE = re.compile(r"Terraform v(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)")


def _parse_version(text: str) -> tuple[int, int, int]:
    match = _VERSION_RE.search(text)
    if not match:
        raise TerraformBinaryError(f"could not parse terraform version from: {text!r}")
    return int(match["major"]), int(match["minor"]), int(match["patch"])


def _summarise_errors(events: list[dict[str, Any]]) -> str:
    messages = []
    for event in events:
        if (
            event.get("type") == "diagnostic"
            and event.get("diagnostic", {}).get("severity") == "error"
        ):
            diag = event["diagnostic"]
            summary = diag.get("summary", "")
            detail = diag.get("detail", "")
            messages.append(f"{summary}: {detail}" if detail else summary)
    return "; ".join(messages)


class TerraformCLI:
    """Async wrapper executing terraform in a per-run workspace directory."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    # -- binary management ---------------------------------------------------

    def binary_path(self) -> str:
        binary = shutil.which(self.settings.terraform_binary)
        if binary is None:
            raise TerraformBinaryError(
                f"terraform binary '{self.settings.terraform_binary}' not found on PATH"
            )
        return binary

    async def check_version(self) -> tuple[int, int, int]:
        """Verify the pinned minimum version (T005: terraform >= 1.9)."""
        binary = self.binary_path()
        proc = await asyncio.create_subprocess_exec(
            binary,
            "version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise TerraformBinaryError(
                f"terraform version check failed: {stderr.decode(errors='replace')}"
            )
        version = _parse_version(stdout.decode(errors="replace"))
        required = _parse_version(f"Terraform v{self.settings.terraform_min_version}")
        if version < required:
            raise TerraformBinaryError(
                f"terraform {version} is below pinned minimum {self.settings.terraform_min_version}"
            )
        return version

    # -- command execution -----------------------------------------------------

    async def run_json(
        self,
        args: list[str],
        *,
        workdir: Path,
        on_event: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Run terraform with ``-json`` output, streaming parsed events.

        ``on_event`` (optional sync or async callable) receives each
        TerraformEvent as it arrives — this is how the worker (T032) streams
        progress into DeploymentStep updates.
        """
        binary = self.binary_path()
        workdir.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            binary,
            *args,
            "-json",
            "-no-color",
            "-input=false",
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
        )
        events: list[dict[str, Any]] = []
        assert proc.stdout is not None and proc.stderr is not None
        async for raw_line in proc.stdout:
            line = raw_line.decode(errors="replace").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            events.append(payload)
            if on_event is not None:
                result = on_event(TerraformEvent(type=payload.get("type", ""), payload=payload))
                if asyncio.iscoroutine(result):
                    await result
        stderr_bytes = await proc.stderr.read()
        returncode = await proc.wait()
        if returncode != 0:
            raise TerraformError(
                " ".join(args), returncode, stderr_bytes.decode(errors="replace"), events
            )
        return events

    async def run_plain(self, args: list[str], *, workdir: Path) -> str:
        """Run terraform without -json (e.g. ``workspace select``)."""
        binary = self.binary_path()
        workdir.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_exec(
            binary,
            *args,
            "-input=false",
            "-no-color",
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env(),
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise TerraformError(
                " ".join(args),
                proc.returncode or -1,
                stderr.decode(errors="replace"),
                [],
            )
        return stdout.decode(errors="replace")

    def _env(self) -> dict[str, str]:
        import os

        env = dict(os.environ)
        # Dev-only LocalStack overrides come from settings, never config YAML.
        if self.settings.aws_endpoint_url:
            env["AWS_ENDPOINT_URL"] = self.settings.aws_endpoint_url
        if self.settings.aws_access_key_id:
            env["AWS_ACCESS_KEY_ID"] = self.settings.aws_access_key_id
        if self.settings.aws_secret_access_key:
            env["AWS_SECRET_ACCESS_KEY"] = self.settings.aws_secret_access_key
        return env

    # -- high-level verbs -------------------------------------------------------

    def workspace_dir(self, run_id: str) -> Path:
        """Per-run workspace directory (R-06: state isolation per run)."""
        return self.settings.workspaces_dir / run_id

    async def init(
        self,
        workdir: Path,
        *,
        backend_config: dict[str, Any] | None = None,
        reconfigure: bool = False,
    ) -> list[dict[str, Any]]:
        args = ["init"]
        if reconfigure:
            args.append("-reconfigure")
        for key, value in (backend_config or {}).items():
            args.append(f"-backend-config={key}={value}")
        return await self.run_json(args, workdir=workdir)

    async def validate(self, workdir: Path) -> list[dict[str, Any]]:
        return await self.run_json(["validate"], workdir=workdir)

    async def plan(
        self,
        workdir: Path,
        *,
        var_files: list[Path] | None = None,
        destroy: bool = False,
        out: str | None = None,
    ) -> list[dict[str, Any]]:
        args = ["plan"]
        if destroy:
            args.append("-destroy")
        if out:
            args.extend(["-out", out])
        for var_file in var_files or []:
            args.extend(["-var-file", str(var_file)])
        return await self.run_json(args, workdir=workdir)

    async def apply(
        self,
        workdir: Path,
        *,
        plan_file: str | None = None,
        auto_approve: bool = True,
        on_event: Any | None = None,
    ) -> list[dict[str, Any]]:
        args = ["apply"]
        if auto_approve:
            args.append("-auto-approve")
        if plan_file:
            args.append(plan_file)
        return await self.run_json(args, workdir=workdir, on_event=on_event)

    async def destroy(
        self, workdir: Path, *, auto_approve: bool = True, on_event: Any | None = None
    ) -> list[dict[str, Any]]:
        args = ["destroy"]
        if auto_approve:
            args.append("-auto-approve")
        return await self.run_json(args, workdir=workdir, on_event=on_event)

    async def select_workspace(self, workdir: Path, workspace: str) -> str:
        """Per-run workspace selection (R-01). Creates when missing."""
        try:
            return await self.run_plain(["workspace", "select", workspace], workdir=workdir)
        except TerraformError:
            return await self.run_plain(["workspace", "new", workspace], workdir=workdir)
