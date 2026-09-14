"""GitOps workflow helpers (T074, US2).

The version-controlled layout is ``platform-configs/<platform-name>/<env>.yaml``.
This module resolves config files from that layout, records git provenance
(``source=git`` + ``git_ref``), and documents the PR-gated change workflow.

The layout is enforced here (path resolution) and documented in
``platform-configs/README.md``. No actual git commands are run — provenance
is supplied by the caller (CLI/API) which knows the checked-out ref.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

#: Environment-type suffix used to name the per-env config file.
ENV_FILE_SUFFIXES = ("development", "test", "uat", "production")


class GitOpsLayoutError(ValueError):
    """Raised when a config path does not conform to the GitOps layout."""


def resolve_config_path(configs_root: Path, platform_name: str, environment: str) -> Path:
    """Resolve ``platform-configs/<platform-name>/<env>.yaml`` (layout enforcement).

    ``environment`` is the config's ``platform.environment`` value. Raises
    ``GitOpsLayoutError`` when the name/env is not layout-conformant.
    """
    if environment not in ENV_FILE_SUFFIXES:
        raise GitOpsLayoutError(f"environment '{environment}' must be one of {ENV_FILE_SUFFIXES}")
    return configs_root / platform_name / f"{environment}.yaml"


def load_gitops_config(configs_root: Path, platform_name: str, environment: str) -> dict[str, Any]:
    """Load a config from the GitOps layout (path enforced)."""
    path = resolve_config_path(configs_root, platform_name, environment)
    if not path.is_file():
        raise GitOpsLayoutError(f"config not found at {path} (GitOps layout)")
    with open(path) as handle:
        parsed = yaml.safe_load(handle)
    if not isinstance(parsed, dict):
        raise GitOpsLayoutError(f"config at {path} must be a YAML mapping")
    return parsed


def git_source(git_ref: str | None) -> str:
    """Provenance marker: git-sourced configs record ``source=git`` + ref."""
    return "git" if git_ref else "api"
