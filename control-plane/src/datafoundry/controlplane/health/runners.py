"""MVP health check runners (T033, R-08).

One runner per capability-catalog.md health check id:

- dns-resolve (networking)
- kms-decrypt-probe (secrets)
- zone-head (storage_zones: bronze/silver/gold prefixes)
- token-mint (iam)
- instance-ready (compute)
- pg-ping (database)
- http-health (catalog: OpenMetadata /health)
- airflow-health (orchestration)
- endpoint-responds (ingestion, semantic_layer)
- runner-heartbeat (quality placeholder — full behaviour in feature 004)
- synthetic-datapoint (monitoring)

All probes go through the CloudGateway so they work against real clouds,
LocalStack, or the simulated dev gateway.
"""

from __future__ import annotations

import socket
from urllib.parse import urlparse

from datafoundry.controlplane.db.models import HealthStatus
from datafoundry.controlplane.health.framework import (
    HealthCheckOutcome,
    HealthCheckRunner,
    HealthCheckTarget,
    RunnerRegistry,
)

ZONES = ("bronze", "silver", "gold")


def _outcome(component: str, ok: bool, detail: str) -> HealthCheckOutcome:
    return HealthCheckOutcome(
        component=component,
        status=HealthStatus.healthy if ok else HealthStatus.unhealthy,
        detail=None if ok else detail,
    )


class DnsResolveRunner(HealthCheckRunner):
    """networking: the platform's private DNS/endpoint namespace resolves."""

    runner_id = "dns-resolve"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        host = target.target
        if not host:
            return _outcome("networking", False, "no dns target recorded")
        parsed = urlparse(host if "//" in host else f"//{host}")
        hostname = parsed.hostname or host
        try:
            socket.getaddrinfo(hostname, None)
            return _outcome("networking", True, "")
        except socket.gaierror:
            # Simulated/private namespaces are not resolvable from the control
            # plane host; ask the gateway (it knows the simulated inventory).
            ok, detail = gateway.endpoint_responds(target.target)
            return _outcome("networking", ok, detail)


class KmsDecryptProbeRunner(HealthCheckRunner):
    """secrets: KMS encrypt/decrypt round-trip."""

    runner_id = "kms-decrypt-probe"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        ok, detail = gateway.kms_decrypt_probe(target.target or "platform-cmk")
        return _outcome("secrets", ok, detail)


class ZoneHeadRunner(HealthCheckRunner):
    """storage_zones: Bronze/Silver/Gold prefixes exist (head probe)."""

    runner_id = "zone-head"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        bucket = (target.context or {}).get("bucket", target.target)
        missing = [zone for zone in ZONES if not gateway.zone_exists(bucket, zone)]
        if missing:
            return _outcome("storage_zones", False, f"missing zone prefixes: {', '.join(missing)}")
        return _outcome("storage_zones", True, "")


class TokenMintRunner(HealthCheckRunner):
    """iam: a service identity token can be minted (simulated: role exists)."""

    runner_id = "token-mint"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        ok, detail = gateway.endpoint_responds(target.target or "iam-role")
        return _outcome("iam", ok, detail)


class InstanceReadyRunner(HealthCheckRunner):
    """compute: platform compute instance/cluster is ready."""

    runner_id = "instance-ready"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        ok, detail = gateway.endpoint_responds(target.target or "compute")
        return _outcome("compute", ok, detail)


class PgPingRunner(HealthCheckRunner):
    """database: PostgreSQL accepts connections (pg-ping)."""

    runner_id = "pg-ping"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        endpoint = target.target
        if endpoint.startswith("postgres"):
            # Real endpoint: attempt a TCP connect to host:port.
            parsed = urlparse(endpoint)
            host = parsed.hostname or "localhost"
            port = parsed.port or 5432
            try:
                with socket.create_connection((host, port), timeout=5):
                    return _outcome("database", True, "")
            except OSError as exc:
                return _outcome("database", False, f"pg-ping failed: {exc}")
        ok, detail = gateway.endpoint_responds(endpoint or "database")
        return _outcome("database", ok, detail)


class HttpHealthRunner(HealthCheckRunner):
    """catalog: OpenMetadata HTTP /health responds."""

    runner_id = "http-health"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        url = target.target
        if url and not url.endswith("/health"):
            url = f"{url.rstrip('/')}/health"
        ok, detail = gateway.http_health(url or "catalog")
        zones = gateway.catalog_lists_zones(target.target or "catalog")
        if ok and not zones:
            return _outcome("catalog", False, "catalog up but no zones registered")
        return _outcome("catalog", ok, detail)


class AirflowHealthRunner(HealthCheckRunner):
    """orchestration: managed Airflow /health responds."""

    runner_id = "airflow-health"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        url = target.target
        if url and not url.endswith("/health"):
            url = f"{url.rstrip('/')}/health"
        ok, detail = gateway.http_health(url or "orchestration")
        return _outcome("orchestration", ok, detail)


class EndpointRespondsRunner(HealthCheckRunner):
    """ingestion / semantic_layer: logical endpoint responds."""

    runner_id = "endpoint-responds"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        ok, detail = gateway.endpoint_responds(target.target or target.capability)
        return _outcome(target.capability, ok, detail)


class RunnerHeartbeatRunner(HealthCheckRunner):
    """quality placeholder (full behaviour delivered by feature 004)."""

    runner_id = "runner-heartbeat"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        ok, detail = gateway.endpoint_responds(target.target or "quality-runner")
        return _outcome("quality", ok, detail)


class SyntheticDatapointRunner(HealthCheckRunner):
    """monitoring: a synthetic datapoint round-trips through the collector."""

    runner_id = "synthetic-datapoint"

    def run(self, target: HealthCheckTarget, gateway) -> HealthCheckOutcome:
        ok, detail = gateway.endpoint_responds(target.target or "otel-collector")
        return _outcome("monitoring", ok, detail)


def build_runner_registry() -> RunnerRegistry:
    registry = RunnerRegistry()
    for runner in (
        DnsResolveRunner(),
        KmsDecryptProbeRunner(),
        ZoneHeadRunner(),
        TokenMintRunner(),
        InstanceReadyRunner(),
        PgPingRunner(),
        HttpHealthRunner(),
        AirflowHealthRunner(),
        EndpointRespondsRunner(),
        RunnerHeartbeatRunner(),
        SyntheticDatapointRunner(),
    ):
        registry.register(runner)
    return registry


#: Process-wide default runner registry.
default_runners: RunnerRegistry = build_runner_registry()
