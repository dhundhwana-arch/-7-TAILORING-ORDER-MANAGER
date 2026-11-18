"""HTTP adapter shells for live cross-module deployment.

NOTE:
- Module 02 (`fabric-catalog-system`) HTTP adapter aligns with the draft contract
  inspected on branch `arena/9fb44bec-fabric-catalog-system`
  (`GET /api/v1/fabrics/by-code/{fabric_id}`).
- Because Modules 03, 04, 05, and 06 do not yet publish verified HTTP endpoints
  on `main`, their HTTP adapters fail safely with `IntegrationError` unless/until
  verified contracts are configured, never inventing fake responses.
"""

from typing import Any

import httpx

from app.adapters.contracts import (
    DesignRecord,
    FabricRecord,
    MeasurementRecord,
    PreviewRecord,
    QuotationRecord,
)
from app.core.enums import FabricSource
from app.core.exceptions import IntegrationError


class HttpFabricCatalogAdapter:
    """HTTP client targeting Module 02 (`GET /api/v1/fabrics/by-code/{fabric_id}`)."""

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def get_fabric(
        self,
        fabric_id: str,
        *,
        variant_id: str | None = None,
        fabric_source: str = FabricSource.CUSTOMER_SUPPLIED.value,
    ) -> FabricRecord | None:
        if fabric_source == FabricSource.CUSTOMER_SUPPLIED.value:
            return FabricRecord(
                fabric_id=fabric_id.strip(),
                variant_id=variant_id,
                fabric_name="Customer-Supplied Fabric",
                fabric_type="Customer Provided",
                sourcing_method=FabricSource.CUSTOMER_SUPPLIED.value,
                availability_status="CUSTOMER_PROVIDED",
            )
        url = f"{self._base_url}/api/v1/fabrics/by-code/{fabric_id.strip()}"
        try:
            resp = httpx.get(url, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise IntegrationError(
                f"Unable to reach Module 02 Fabric Catalog service: {exc}"
            ) from exc
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise IntegrationError(
                f"Module 02 Fabric Catalog returned HTTP {resp.status_code}."
            )
        data: dict[str, Any] = resp.json()
        return FabricRecord(
            fabric_id=str(data.get("fabric_id", fabric_id)),
            variant_id=variant_id,
            fabric_name=str(data.get("fabric_name", "Catalogue Fabric")),
            fabric_type=str(data.get("fabric_type", "Unknown")),
            sourcing_method=str(
                data.get("sourcing_method", FabricSource.BUSINESS_INVENTORY.value)
            ),
            availability_status=str(data.get("availability_status", "AVAILABLE")),
            is_active=bool(data.get("is_active", True)),
        )


class UnverifiedHttpAdapterBase:
    """Fails explicitly until the owning sibling module publishes a verified HTTP contract."""

    module_label: str = "Upstream Module"

    def __init__(self, base_url: str, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    def _raise_unverified(self) -> None:
        raise IntegrationError(
            f"{self.module_label} HTTP contract is not yet verified on `main`. "
            "Configure INTEGRATION_MODE=mock for development/testing or register "
            "a verified adapter once the upstream module contract is approved."
        )


class HttpPricingAdapter(UnverifiedHttpAdapterBase):
    module_label = "Module 05 (Clothing Price Engine)"

    def get_quotation(self, quotation_id: str) -> QuotationRecord | None:
        self._raise_unverified()


class HttpMeasurementAdapter(UnverifiedHttpAdapterBase):
    module_label = "Module 06 (Measurement Guide)"

    def get_measurement(self, measurement_id: str) -> MeasurementRecord | None:
        self._raise_unverified()


class HttpDesignConfigAdapter(UnverifiedHttpAdapterBase):
    module_label = "Module 03 (2D Clothing Designer)"

    def get_design(self, design_id: str) -> DesignRecord | None:
        self._raise_unverified()


class HttpPreviewReferenceAdapter(UnverifiedHttpAdapterBase):
    module_label = "Module 04 (3D Clothing Preview)"

    def get_preview(self, preview_id: str) -> PreviewRecord | None:
        self._raise_unverified()
