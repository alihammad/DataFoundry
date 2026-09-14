"""GCP provider adapter (T012)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from datafoundry.controlplane.providers.base import (
    CallerIdentity,
    ProviderAdapter,
    ProviderAuthError,
    StateBackendConfig,
)
from datafoundry.controlplane.providers.matrix import ModuleAvailabilityMatrix

#: MVP GCP region list.
GCP_REGIONS: tuple[str, ...] = (
    "us-central1",
    "us-east1",
    "us-east4",
    "us-west1",
    "us-west2",
    "northamerica-northeast1",
    "southamerica-east1",
    "europe-west1",
    "europe-west2",
    "europe-west3",
    "europe-west4",
    "europe-north1",
    "asia-south1",
    "asia-southeast1",
    "asia-east1",
    "asia-northeast1",
    "australia-southeast1",
)

#: Capabilities with known GCP region restrictions (managed-service
#: availability). Everything else is available in every region above.
_GCP_REGION_RESTRICTIONS: dict[str, frozenset[str]] = {
    # Cloud Composer (managed Airflow) availability.
    "orchestration": frozenset(
        {
            "us-central1",
            "us-east1",
            "us-east4",
            "us-west1",
            "us-west2",
            "northamerica-northeast1",
            "southamerica-east1",
            "europe-west1",
            "europe-west2",
            "europe-west3",
            "europe-west4",
            "europe-north1",
            "asia-south1",
            "asia-southeast1",
            "asia-east1",
            "asia-northeast1",
            "australia-southeast1",
        }
    ),
}


class GcpAdapter(ProviderAdapter):
    provider_id = "gcp"

    def __init__(
        self,
        *,
        terraform_root: Path | None = None,
        project: str = "",
    ) -> None:
        self._matrix = ModuleAvailabilityMatrix(
            provider_id=self.provider_id,
            regions=GCP_REGIONS,
            terraform_root=terraform_root,
            region_restrictions=_GCP_REGION_RESTRICTIONS,
        )
        self._project = project

    # -- regions & matrix ---------------------------------------------------

    def regions(self) -> tuple[str, ...]:
        return GCP_REGIONS

    def region_supports(self, region: str, capability_key: str) -> bool:
        return self._matrix.supports(region, capability_key)

    def regions_for_capability(self, capability_key: str) -> tuple[str, ...]:
        return self._matrix.regions_for(capability_key)

    # -- state backend (R-05: GCS with native object locking) ----------------

    def state_backend(
        self, *, platform_name: str, environment: str, run_id: str, region: str
    ) -> StateBackendConfig:
        bucket = f"datafoundry-{platform_name}-{environment}-tfstate"
        return StateBackendConfig(
            type="gcs",
            config={
                "bucket": bucket,
                "prefix": f"runs/{run_id}",
                # GCS backend uses native object locking for state locking
                # (R-05); CMEK encryption via the storage module's key.
            },
        )

    # -- credential probe (R-09/FR-018: token introspection) ----------------

    def probe_credentials(self, session: Any | None = None) -> CallerIdentity:
        import google.auth  # local import: keep module import cheap
        import google.auth.transport.requests
        from google.auth.exceptions import GoogleAuthError

        try:
            credentials, project = google.auth.default()
            request = google.auth.transport.requests.Request()
            credentials.refresh(request)
        except GoogleAuthError as exc:
            raise ProviderAuthError(f"GCP credential probe failed: {exc}") from exc

        account_id = self._project or project or ""
        if not account_id:
            raise ProviderAuthError("GCP project could not be determined from credentials")
        principal = (
            getattr(credentials, "service_account_email", None)
            or getattr(credentials, "_subject", None)
            or "user"
        )
        return CallerIdentity(
            provider=self.provider_id,
            account_id=account_id,
            identity_arn_or_principal=str(principal),
            authenticated=True,
        )

    def cloud_scope_id(self, identity: CallerIdentity) -> str:
        return identity.account_id
