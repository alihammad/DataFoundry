"""API router: capabilities + region matrix (T079, deployment-api.md §3).

``GET /api/v1/capabilities``            — registry catalog incl. providers.
``GET /api/v1/providers/{p}/regions``   — generated region-capability matrix
(``?capability=`` filters).
"""

from __future__ import annotations

from datafoundry.controlplane.api.auth import ACTION_READ_PLATFORM, require_action
from datafoundry.controlplane.capabilities.registry import default_registry
from datafoundry.controlplane.providers.base import ProviderNotFoundError, default_providers
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

router = APIRouter(tags=["capabilities"])


class CapabilityView(BaseModel):
    key: str
    display_name: str
    selectable: bool
    depends_on: list[str]
    providers: list[str]


class CapabilityCatalog(BaseModel):
    items: list[CapabilityView]


@router.get(
    "/capabilities",
    response_model=CapabilityCatalog,
    dependencies=[Depends(require_action(ACTION_READ_PLATFORM))],
)
def list_capabilities() -> CapabilityCatalog:
    provider_ids = list(default_providers.provider_ids())
    items = [
        CapabilityView(
            key=capability.key,
            display_name=capability.display_name,
            selectable=capability.selectable,
            depends_on=list(capability.depends_on),
            providers=provider_ids,
        )
        for capability in sorted(default_registry.capabilities.values(), key=lambda c: c.key)
    ]
    return CapabilityCatalog(items=items)


class RegionView(BaseModel):
    id: str
    capabilities_supported: list[str]


class RegionMatrix(BaseModel):
    regions: list[RegionView]


@router.get(
    "/providers/{provider}/regions",
    response_model=RegionMatrix,
    dependencies=[Depends(require_action(ACTION_READ_PLATFORM))],
)
def list_regions(
    provider: str,
    capability: str | None = Query(default=None),
) -> RegionMatrix:
    try:
        adapter = default_providers.get(provider)
    except ProviderNotFoundError:
        from datafoundry.controlplane.api.errors import NotFoundError

        raise NotFoundError(f"unknown provider '{provider}'") from None

    regions: list[RegionView] = []
    for region in adapter.regions():
        if capability is not None:
            if not adapter.region_supports(region, capability):
                continue
            supported = [capability]
        else:
            supported = sorted(
                key for key in default_registry.capabilities if adapter.region_supports(region, key)
            )
        regions.append(RegionView(id=region, capabilities_supported=supported))
    return RegionMatrix(regions=regions)
