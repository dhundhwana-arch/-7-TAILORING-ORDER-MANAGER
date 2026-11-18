"""Dependency-injectable registry bundling cross-module adapters."""

from dataclasses import dataclass

from app.adapters.contracts import (
    DesignConfigAdapter,
    FabricCatalogAdapter,
    MeasurementAdapter,
    NotificationDispatchResult,
    NotificationProvider,
    PreviewReferenceAdapter,
    PricingAdapter,
)
from app.adapters.http_adapters import (
    HttpDesignConfigAdapter,
    HttpFabricCatalogAdapter,
    HttpMeasurementAdapter,
    HttpPreviewReferenceAdapter,
    HttpPricingAdapter,
)
from app.adapters.mock_adapters import (
    MockDesignConfigAdapter,
    MockFabricCatalogAdapter,
    MockMeasurementAdapter,
    MockNotificationProvider,
    MockPreviewReferenceAdapter,
    MockPricingAdapter,
)
from app.core.config import Settings


class DisabledNotificationProvider:
    """No-op provider recording notifications as SKIPPED without external delivery."""

    def dispatch(
        self,
        *,
        notification_ref: str,
        event_type: str,
        channel: str,
        recipient_ref: str,
        payload: dict,
    ) -> NotificationDispatchResult:
        return NotificationDispatchResult(
            delivered=False,
            provider_name="disabled",
            status_label="SKIPPED",
        )


@dataclass
class AdapterRegistry:
    pricing: PricingAdapter
    measurement: MeasurementAdapter
    fabric: FabricCatalogAdapter
    design: DesignConfigAdapter
    preview: PreviewReferenceAdapter
    notification: NotificationProvider


def build_adapter_registry(settings: Settings) -> AdapterRegistry:
    notification_provider: NotificationProvider = (
        MockNotificationProvider()
        if settings.NOTIFICATION_PROVIDER == "mock"
        else DisabledNotificationProvider()
    )

    if settings.INTEGRATION_MODE == "http":
        t = settings.INTEGRATION_HTTP_TIMEOUT_SECONDS
        return AdapterRegistry(
            pricing=HttpPricingAdapter(settings.MODULE_05_PRICING_BASE_URL, t),
            measurement=HttpMeasurementAdapter(
                settings.MODULE_06_MEASUREMENT_BASE_URL, t
            ),
            fabric=HttpFabricCatalogAdapter(settings.MODULE_02_FABRIC_BASE_URL, t),
            design=HttpDesignConfigAdapter(settings.MODULE_03_DESIGN_BASE_URL, t),
            preview=HttpPreviewReferenceAdapter(settings.MODULE_04_PREVIEW_BASE_URL, t),
            notification=notification_provider,
        )

    return AdapterRegistry(
        pricing=MockPricingAdapter(),
        measurement=MockMeasurementAdapter(),
        fabric=MockFabricCatalogAdapter(),
        design=MockDesignConfigAdapter(),
        preview=MockPreviewReferenceAdapter(),
        notification=notification_provider,
    )
