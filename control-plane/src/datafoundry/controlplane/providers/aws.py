"""AWS provider adapter (T012)."""

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

#: MVP AWS region list. The region-capability matrix (which capability is
#: supported where) is generated from actual module availability (T061), not
#: hand-maintained per region.
AWS_REGIONS: tuple[str, ...] = (
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "ca-central-1",
    "eu-west-1",
    "eu-west-2",
    "eu-west-3",
    "eu-central-1",
    "eu-north-1",
    "ap-south-1",
    "ap-southeast-1",
    "ap-southeast-2",
    "ap-northeast-1",
    "ap-northeast-2",
    "sa-east-1",
)

#: Capabilities with known AWS region restrictions (managed-service
#: availability). Everything else is available in every region above.
_AWS_REGION_RESTRICTIONS: dict[str, frozenset[str]] = {
    # MWAA (managed Airflow) is not available in every region.
    "orchestration": frozenset(
        {
            "us-east-1",
            "us-east-2",
            "us-west-2",
            "ca-central-1",
            "eu-west-1",
            "eu-west-2",
            "eu-west-3",
            "eu-central-1",
            "eu-north-1",
            "ap-south-1",
            "ap-southeast-1",
            "ap-southeast-2",
            "ap-northeast-1",
            "ap-northeast-2",
            "sa-east-1",
        }
    ),
}


class AwsAdapter(ProviderAdapter):
    provider_id = "aws"

    def __init__(
        self,
        *,
        terraform_root: Path | None = None,
        endpoint_url: str = "",
        region: str = "us-east-1",
        access_key_id: str = "",
        secret_access_key: str = "",
    ) -> None:
        self._matrix = ModuleAvailabilityMatrix(
            provider_id=self.provider_id,
            regions=AWS_REGIONS,
            terraform_root=terraform_root,
            region_restrictions=_AWS_REGION_RESTRICTIONS,
        )
        # Dev-only overrides (LocalStack). Empty endpoint_url => real AWS.
        self._endpoint_url = endpoint_url
        self._region = region
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key

    # -- regions & matrix ---------------------------------------------------

    def regions(self) -> tuple[str, ...]:
        return AWS_REGIONS

    def region_supports(self, region: str, capability_key: str) -> bool:
        return self._matrix.supports(region, capability_key)

    def regions_for_capability(self, capability_key: str) -> tuple[str, ...]:
        return self._matrix.regions_for(capability_key)

    # -- state backend (R-05: S3 + DynamoDB lock, in the platform's account) --

    def state_backend(
        self, *, platform_name: str, environment: str, run_id: str, region: str
    ) -> StateBackendConfig:
        bucket = f"datafoundry-{platform_name}-{environment}-tfstate"
        return StateBackendConfig(
            type="s3",
            config={
                "bucket": bucket,
                "key": f"runs/{run_id}/terraform.tfstate",
                "region": region,
                "dynamodb_table": f"datafoundry-{platform_name}-{environment}-tflock",
                "encrypt": True,
                # Versioned bucket (created by the storage module) gives state
                # rollback if an apply corrupts it (R-05).
            },
        )

    # -- credential probe (R-09/FR-018: STS GetCallerIdentity) --------------

    def probe_credentials(self, session: Any | None = None) -> CallerIdentity:
        import boto3  # local import: keep module import cheap
        from botocore.exceptions import BotoCoreError, ClientError

        kwargs: dict[str, Any] = {"region_name": self._region}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        if self._access_key_id and self._secret_access_key:
            kwargs["aws_access_key_id"] = self._access_key_id
            kwargs["aws_secret_access_key"] = self._secret_access_key
        client = session.client("sts", **kwargs) if session else boto3.client("sts", **kwargs)
        try:
            identity = client.get_caller_identity()
        except (ClientError, BotoCoreError) as exc:
            raise ProviderAuthError(f"AWS STS GetCallerIdentity failed: {exc}") from exc
        return CallerIdentity(
            provider=self.provider_id,
            account_id=identity["Account"],
            identity_arn_or_principal=identity["Arn"],
            authenticated=True,
        )

    def cloud_scope_id(self, identity: CallerIdentity) -> str:
        return identity.account_id
