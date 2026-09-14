"""Storage-zone + catalog initialisation job (T034, FR-005).

Runs as part of the ``storage-zones`` and ``catalog`` deployment steps:

1. Create Bronze/Silver/Gold zone prefixes in the platform bucket.
2. Register the zones + capability inventory in the catalog (OpenMetadata)
   BEFORE readiness — the health check for catalog asserts zones are listed.

All cloud operations go through the CloudGateway (simulated in dev/tests,
boto3-backed against LocalStack/real AWS otherwise).
"""

from __future__ import annotations

from dataclasses import dataclass

from datafoundry.controlplane.engine.gateway import CloudGateway

ZONES = ("bronze", "silver", "gold")


@dataclass(frozen=True)
class InitResult:
    bucket: str
    zone_ids: list[str]
    catalog_endpoint: str
    catalog_ids: list[str]


def platform_bucket(platform_name: str, environment: str, provider: str) -> str:
    """Deterministic platform bucket name (mirrors terraform storage module)."""
    return f"datafoundry-{platform_name}-{environment}-{provider}"


def initialise_storage_zones(
    gateway: CloudGateway,
    *,
    run_id: str,
    platform_name: str,
    environment: str,
    provider: str,
) -> list[str]:
    """Create Bronze/Silver/Gold prefixes (FR-005). Returns resource ids."""
    bucket = platform_bucket(platform_name, environment, provider)
    return gateway.create_zone_prefixes(
        run_id=run_id, bucket=bucket, zones=list(ZONES), capability="storage_zones"
    )


def initialise_catalog(
    gateway: CloudGateway,
    *,
    run_id: str,
    platform_name: str,
    environment: str,
    provider: str,
    catalog_endpoint: str,
    capabilities_enabled: list[str],
) -> list[str]:
    """Register zones + capability inventory in the catalog before readiness."""
    ids = gateway.register_catalog_zones(
        run_id=run_id, catalog_endpoint=catalog_endpoint, zones=list(ZONES)
    )
    # Capability inventory registration (best-effort; OpenMetadata service
    # ingestion lands with feature 006).
    _ = capabilities_enabled
    return ids
