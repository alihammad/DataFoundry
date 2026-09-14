"""Storage utilisation collection (T081, US3).

Reports Bronze/Silver/Gold byte counts per zone via the provider gateway
(``CloudGateway.zone_bytes``). The simulated gateway returns deterministic
counts derived from recorded zone-prefix resources; the AWS gateway sums
object sizes under each zone prefix (ListObjectsV2).
"""

from __future__ import annotations

from dataclasses import dataclass

from datafoundry.controlplane.engine.gateway import CloudGateway
from datafoundry.controlplane.engine.init_jobs import platform_bucket

ZONES = ("bronze", "silver", "gold")


@dataclass(frozen=True)
class StorageUtilisation:
    """Byte counts per zone (deployment-api.md §1 storage_utilisation)."""

    bronze_bytes: int = 0
    silver_bytes: int = 0
    gold_bytes: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "bronze_bytes": self.bronze_bytes,
            "silver_bytes": self.silver_bytes,
            "gold_bytes": self.gold_bytes,
        }


def collect_utilisation(
    gateway: CloudGateway, *, platform_name: str, environment: str, provider: str
) -> StorageUtilisation:
    """Sum byte counts across Bronze/Silver/Gold for a platform bucket."""
    bucket = platform_bucket(platform_name, environment, provider)
    counts = {zone: gateway.zone_bytes(bucket, zone) for zone in ZONES}
    return StorageUtilisation(
        bronze_bytes=counts["bronze"],
        silver_bytes=counts["silver"],
        gold_bytes=counts["gold"],
    )
