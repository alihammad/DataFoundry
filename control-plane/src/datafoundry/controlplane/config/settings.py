"""Environment/settings management (T021).

All dev-only knobs (LocalStack endpoint, fault injection, auth bypass) live
here as ``DF_*`` environment variables — NEVER in the platform config YAML,
which stays cloud-neutral and strict (see contracts/platform-config-schema.md).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the control plane, sourced from the environment."""

    # Persistence
    database_url: str = "postgresql+psycopg://datafoundry:datafoundry@localhost:5432/datafoundry"

    # Terraform execution (R-01)
    terraform_binary: str = "terraform"
    terraform_min_version: str = "1.9.0"
    # Root directory containing terraform/{provider}/{capability} modules and
    # the per-run workspaces/ directory.
    terraform_root: Path = field(
        default_factory=lambda: Path(os.environ.get("DF_TERRAFORM_ROOT", Path.cwd() / "terraform"))
    )

    # Credentials mode: "ambient" (instance role / workload identity) or
    # "per_session" (short-lived, supplied per request; never persisted — R-09).
    credentials_mode: str = "ambient"

    # Dev-only AWS overrides (LocalStack emulator). Empty => real AWS.
    aws_endpoint_url: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # Dev-only fault injection (quickstart Scenario 3): when enabled, the
    # deployment worker fails the step named by ``fault_injection_step``
    # (default "orchestration") with a simulated error.
    fault_injection: bool = False
    fault_injection_step: str = "orchestration"

    # Simulated cloud mode: when true (default in dev/tests) the worker
    # executes steps against the in-memory SimulatedCloudGateway instead of
    # spawning terraform; LocalStack E2E (quickstart Scenarios 2-3) runs with
    # DF_SIMULATE_CLOUD=0 + DF_AWS_ENDPOINT_URL set.
    simulate_cloud: bool = True

    # Auth: "cloud_iam" (federated identity verification) or "dev" (static
    # local identity, development only).
    auth_mode: str = "dev"
    dev_identity: str = "dev@datafoundry.local"

    # Observability
    log_level: str = "INFO"
    log_json: bool = True
    otel_enabled: bool = True
    otel_exporter_otlp_endpoint: str = ""
    service_name: str = "datafoundry-controlplane"
    service_version: str = "0.1.0"

    # API
    api_prefix: str = "/api/v1"

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            database_url=env.get("DF_DATABASE_URL", env.get("DATABASE_URL", cls.database_url)),
            terraform_binary=env.get("DF_TERRAFORM_BINARY", "terraform"),
            terraform_min_version=env.get("DF_TERRAFORM_MIN_VERSION", "1.9.0"),
            terraform_root=Path(env.get("DF_TERRAFORM_ROOT", str(Path.cwd() / "terraform"))),
            credentials_mode=env.get("DF_CREDENTIALS_MODE", "ambient"),
            aws_endpoint_url=env.get("DF_AWS_ENDPOINT_URL", ""),
            aws_access_key_id=env.get("DF_AWS_ACCESS_KEY_ID", ""),
            aws_secret_access_key=env.get("DF_AWS_SECRET_ACCESS_KEY", ""),
            aws_region=env.get("DF_AWS_REGION", "us-east-1"),
            fault_injection=_env_bool("DF_FAULT_INJECTION", False),
            fault_injection_step=env.get("DF_FAULT_INJECTION_STEP", "orchestration"),
            simulate_cloud=_env_bool("DF_SIMULATE_CLOUD", True),
            auth_mode=env.get("DF_AUTH_MODE", "dev"),
            dev_identity=env.get("DF_DEV_IDENTITY", "dev@datafoundry.local"),
            log_level=env.get("DF_LOG_LEVEL", "INFO"),
            log_json=_env_bool("DF_LOG_JSON", True),
            otel_enabled=_env_bool("DF_OTEL_ENABLED", True),
            otel_exporter_otlp_endpoint=env.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            service_name=env.get("DF_SERVICE_NAME", "datafoundry-controlplane"),
            service_version=env.get("DF_SERVICE_VERSION", "0.1.0"),
            api_prefix=env.get("DF_API_PREFIX", "/api/v1"),
        )

    @property
    def workspaces_dir(self) -> Path:
        """Per-run Terraform workspace root (R-06: state isolation per run)."""
        return self.terraform_root / "workspaces"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached process-wide settings. Call ``get_settings.cache_clear()`` in tests."""
    return Settings.from_env()
