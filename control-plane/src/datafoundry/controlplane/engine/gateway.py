"""Cloud gateway abstraction for init jobs, health probes and simulation.

The worker/health framework never talks to a cloud SDK directly — it goes
through a :class:`CloudGateway`. Two implementations:

- :class:`SimulatedCloudGateway` — in-memory inventory used by dev mode and
  tests (no terraform binary / LocalStack required). Tracks every resource a
  run "creates" so retry/rollback semantics (zero orphans, SC-005) and zone/
  catalog initialisation (FR-005) are fully exercisable offline.
- :class:`AwsCloudGateway` — boto3-backed probes against real AWS/LocalStack
  (S3 head-object for zones, KMS decrypt probe, HTTP health endpoints).

Adding GCP live probes = a new gateway class; no core changes (FR-015).
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResourceRecord:
    """One simulated cloud resource created by a run."""

    run_id: str
    kind: str  # bucket, zone_prefix, kms_key, catalog_zone, endpoint, ...
    identifier: str
    capability: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class CloudGateway(abc.ABC):
    """Operations the engine needs outside Terraform."""

    @abc.abstractmethod
    def create_zone_prefixes(
        self, *, run_id: str, bucket: str, zones: list[str], capability: str
    ) -> list[str]:
        """Create Bronze/Silver/Gold zone prefixes (FR-005). Returns ids."""

    @abc.abstractmethod
    def register_catalog_zones(
        self, *, run_id: str, catalog_endpoint: str, zones: list[str]
    ) -> list[str]:
        """Register storage zones + capability inventory in the catalog."""

    @abc.abstractmethod
    def zone_exists(self, bucket: str, zone: str) -> bool:
        """Health probe: zone prefix head (zone-head runner)."""

    @abc.abstractmethod
    def catalog_lists_zones(self, catalog_endpoint: str) -> list[str]:
        """Health probe: zones visible in the catalog."""

    @abc.abstractmethod
    def http_health(self, url: str) -> tuple[bool, str]:
        """Generic HTTP health probe -> (healthy, detail)."""

    @abc.abstractmethod
    def kms_decrypt_probe(self, key_ref: str) -> tuple[bool, str]:
        """KMS round-trip probe (kms-decrypt-probe runner)."""

    @abc.abstractmethod
    def endpoint_responds(self, endpoint: str) -> tuple[bool, str]:
        """endpoint-responds runner probe."""

    @abc.abstractmethod
    def zone_bytes(self, bucket: str, zone: str) -> int:
        """Storage utilisation probe: byte count under a zone prefix (T081)."""

    @abc.abstractmethod
    def destroy_run_resources(self, run_id: str) -> int:
        """Remove every resource created by ``run_id`` (scoped rollback,
        R-06/SC-005). Returns the number of resources removed."""

    @abc.abstractmethod
    def resources_for_run(self, run_id: str) -> list[ResourceRecord]:
        """Inventory of a run's resources (partial-state inspection)."""


class SimulatedCloudGateway(CloudGateway):
    """In-memory cloud inventory (dev mode / tests)."""

    def __init__(self) -> None:
        self._resources: list[ResourceRecord] = []
        self._catalog_zones: dict[str, list[str]] = {}
        self._unhealthy: set[str] = set()  # test hook: force probes to fail

    # -- test hooks ---------------------------------------------------------

    def mark_unhealthy(self, identifier: str) -> None:
        self._unhealthy.add(identifier)

    def mark_healthy(self, identifier: str) -> None:
        self._unhealthy.discard(identifier)

    # -- mutations ------------------------------------------------------------

    def _add(self, record: ResourceRecord) -> str:
        self._resources.append(record)
        return f"{record.kind}:{record.identifier}"

    def create_zone_prefixes(
        self, *, run_id: str, bucket: str, zones: list[str], capability: str
    ) -> list[str]:
        ids = []
        for zone in zones:
            identifier = f"{bucket}/{zone}/"
            ids.append(
                self._add(
                    ResourceRecord(
                        run_id=run_id,
                        kind="zone_prefix",
                        identifier=identifier,
                        capability=capability,
                        meta={"bucket": bucket, "zone": zone},
                    )
                )
            )
        return ids

    def register_catalog_zones(
        self, *, run_id: str, catalog_endpoint: str, zones: list[str]
    ) -> list[str]:
        registered = self._catalog_zones.setdefault(catalog_endpoint, [])
        ids = []
        for zone in zones:
            if zone not in registered:
                registered.append(zone)
            ids.append(
                self._add(
                    ResourceRecord(
                        run_id=run_id,
                        kind="catalog_zone",
                        identifier=f"{catalog_endpoint}#{zone}",
                        capability="catalog",
                        meta={"zone": zone},
                    )
                )
            )
        return ids

    def destroy_run_resources(self, run_id: str) -> int:
        before = len(self._resources)
        kept: list[ResourceRecord] = []
        removed_catalog_keys: list[tuple[str, str]] = []
        for record in self._resources:
            if record.run_id == run_id:
                if record.kind == "catalog_zone":
                    endpoint, _, zone = record.identifier.partition("#")
                    removed_catalog_keys.append((endpoint, zone))
            else:
                kept.append(record)
        self._resources = kept
        for endpoint, zone in removed_catalog_keys:
            zones = self._catalog_zones.get(endpoint, [])
            if zone in zones:
                zones.remove(zone)
        return before - len(kept)

    # -- probes -----------------------------------------------------------------

    def _healthy(self, identifier: str) -> bool:
        return identifier not in self._unhealthy

    def zone_exists(self, bucket: str, zone: str) -> bool:
        identifier = f"{bucket}/{zone}/"
        return any(
            r.kind == "zone_prefix" and r.identifier == identifier for r in self._resources
        ) and self._healthy(identifier)

    def catalog_lists_zones(self, catalog_endpoint: str) -> list[str]:
        if not self._healthy(catalog_endpoint):
            return []
        return list(self._catalog_zones.get(catalog_endpoint, []))

    def http_health(self, url: str) -> tuple[bool, str]:
        if self._healthy(url):
            return True, "200 OK (simulated)"
        return False, "endpoint unreachable (simulated)"

    def kms_decrypt_probe(self, key_ref: str) -> tuple[bool, str]:
        if self._healthy(f"kms:{key_ref}"):
            return True, "decrypt round-trip ok (simulated)"
        return False, "kms decrypt failed (simulated)"

    def endpoint_responds(self, endpoint: str) -> tuple[bool, str]:
        if self._healthy(endpoint):
            return True, "responds (simulated)"
        return False, "no response (simulated)"

    def zone_bytes(self, bucket: str, zone: str) -> int:
        # Deterministic per-zone byte count derived from recorded zone-prefix
        # resources: each prefix contributes a fixed amount (simulated util).
        prefix = f"{bucket}/{zone}/"
        count = sum(
            1 for r in self._resources if r.kind == "zone_prefix" and r.identifier == prefix
        )
        return count * 1024  # 1 KiB per recorded prefix (simulated)

    def resources_for_run(self, run_id: str) -> list[ResourceRecord]:
        return [r for r in self._resources if r.run_id == run_id]


class AwsCloudGateway(CloudGateway):
    """boto3-backed gateway for real AWS / LocalStack (dev emulator).

    Simulation of *provisioning* is still Terraform's job; this gateway only
    performs init jobs (zone prefixes, catalog registration) and health
    probes. Falls back to an inner SimulatedCloudGateway for catalog
    registration when no OpenMetadata endpoint is reachable (R-04: catalog
    runs containerised; endpoint provided by the catalog module output).
    """

    def __init__(
        self,
        *,
        endpoint_url: str = "",
        region: str = "us-east-1",
        access_key_id: str = "",
        secret_access_key: str = "",
    ) -> None:
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._sim = SimulatedCloudGateway()
        self._clients: dict[str, Any] = {}

    def _client(self, service: str) -> Any:
        if service not in self._clients:
            import boto3

            kwargs: dict[str, Any] = {"region_name": self._region}
            if self._endpoint_url:
                kwargs["endpoint_url"] = self._endpoint_url
            if self._access_key_id and self._secret_access_key:
                kwargs["aws_access_key_id"] = self._access_key_id
                kwargs["aws_secret_access_key"] = self._secret_access_key
            self._clients[service] = boto3.client(service, **kwargs)
        return self._clients[service]

    # -- init jobs -----------------------------------------------------------

    def create_zone_prefixes(
        self, *, run_id: str, bucket: str, zones: list[str], capability: str
    ) -> list[str]:
        s3 = self._client("s3")
        ids = []
        for zone in zones:
            key = f"{zone}/.datafoundry-keep"
            s3.put_object(Bucket=bucket, Key=key, Body=b"")
            ids.append(f"zone_prefix:{bucket}/{zone}/")
            self._sim._add(
                ResourceRecord(
                    run_id=run_id,
                    kind="zone_prefix",
                    identifier=f"{bucket}/{zone}/",
                    capability=capability,
                    meta={"bucket": bucket, "zone": zone},
                )
            )
        return ids

    def register_catalog_zones(
        self, *, run_id: str, catalog_endpoint: str, zones: list[str]
    ) -> list[str]:
        # OpenMetadata ingestion is delivered via its REST API; MVP records
        # registration in the simulated inventory and best-effort pings the
        # endpoint (full metadata bootstrap lands with feature 006).
        self.http_health(f"{catalog_endpoint}/health")
        return self._sim.register_catalog_zones(
            run_id=run_id, catalog_endpoint=catalog_endpoint, zones=zones
        )

    # -- probes ---------------------------------------------------------------

    def zone_exists(self, bucket: str, zone: str) -> bool:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self._client("s3").head_object(Bucket=bucket, Key=f"{zone}/.datafoundry-keep")
            return True
        except (ClientError, BotoCoreError):
            return False

    def catalog_lists_zones(self, catalog_endpoint: str) -> list[str]:
        return self._sim.catalog_lists_zones(catalog_endpoint)

    def http_health(self, url: str) -> tuple[bool, str]:
        import urllib.error
        import urllib.request

        try:
            with urllib.request.urlopen(url, timeout=10) as response:  # noqa: S310
                return 200 <= response.status < 500, f"HTTP {response.status}"
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return False, str(exc)

    def kms_decrypt_probe(self, key_ref: str) -> tuple[bool, str]:
        from botocore.exceptions import BotoCoreError, ClientError

        kms = self._client("kms")
        try:
            plaintext = b"datafoundry-health-probe"
            encrypted = kms.encrypt(KeyId=key_ref, Plaintext=plaintext)
            decrypted = kms.decrypt(CiphertextBlob=encrypted["CiphertextBlob"])
            ok = decrypted["Plaintext"] == plaintext
            return ok, "decrypt round-trip ok" if ok else "plaintext mismatch"
        except (ClientError, BotoCoreError) as exc:
            return False, str(exc)

    def zone_bytes(self, bucket: str, zone: str) -> int:
        from botocore.exceptions import BotoCoreError, ClientError

        s3 = self._client("s3")
        total = 0
        try:
            paginator = s3.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=f"{zone}/"):
                for obj in page.get("Contents", []):
                    total += obj.get("Size", 0)
        except (ClientError, BotoCoreError):
            return 0
        return total

    def endpoint_responds(self, endpoint: str) -> tuple[bool, str]:
        if endpoint.startswith("http://") or endpoint.startswith("https://"):
            return self.http_health(endpoint)
        # Non-HTTP endpoints (e.g. DB): treat presence as responding; the
        # capability's own runner (pg-ping etc.) does the deep probe.
        return bool(endpoint), "endpoint present"

    # -- rollback ---------------------------------------------------------------

    def destroy_run_resources(self, run_id: str) -> int:
        # Terraform destroy in the run workspace removes cloud resources
        # (engine/recovery.py); the gateway only clears its inventory.
        return self._sim.destroy_run_resources(run_id)

    def resources_for_run(self, run_id: str) -> list[ResourceRecord]:
        return self._sim.resources_for_run(run_id)


def build_gateway(settings: Any) -> CloudGateway:
    """Gateway per settings: simulated in dev/test, AWS-backed otherwise."""
    simulate = getattr(settings, "simulate_cloud", True)
    if simulate:
        return SimulatedCloudGateway()
    return AwsCloudGateway(
        endpoint_url=settings.aws_endpoint_url,
        region=settings.aws_region,
        access_key_id=settings.aws_access_key_id,
        secret_access_key=settings.aws_secret_access_key,
    )
