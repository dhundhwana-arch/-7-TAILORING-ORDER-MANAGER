"""Clearly labelled mock/fixture adapters for isolated development and testing.

STRICT GUARANTEES:
1. Contains synthetic illustrative identifiers ONLY (`CUS-001`, `DSG-001`, `FAB-001`,
   `MEA-001`, `QUO-001`, etc.) — zero personal customer data.
2. Never independently computes prices; only returns pre-registered Module 05
   quotation fixtures.
3. `MockNotificationProvider` never sends real SMS, Email, or WhatsApp messages.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.adapters.contracts import (
    DesignRecord,
    FabricRecord,
    MeasurementRecord,
    NotificationDispatchResult,
    PreviewRecord,
    QuotationRecord,
)
from app.core.enums import FabricSource
from app.core.exceptions import IntegrationError


class MockPricingAdapter:
    """Temporary replaceable Module 05 adapter backed by synthetic quotation fixtures."""

    def __init__(self) -> None:
        now = datetime(2026, 11, 18, 9, 0, tzinfo=timezone.utc)
        self._simulate_failure: bool = False
        self._quotations: dict[str, QuotationRecord] = {
            "QUO-001": QuotationRecord(
                quotation_id="QUO-001",
                quoted_amount=Decimal("450.00"),
                currency="INR",
                price_breakdown={
                    "stitching_fee": "450.00",
                    "fabric_component": "0.00",
                    "basis": "reported_standard_shirt_pant_set_fixture",
                },
                quotation_status="VALID",
                pricing_config_version="v1.0.0-mock",
                quotation_timestamp=now,
                valid_until=now + timedelta(days=30),
                customer_ref=None,
            ),
            "QUO-002": QuotationRecord(
                quotation_id="QUO-002",
                quoted_amount=Decimal("500.00"),
                currency="INR",
                price_breakdown={
                    "stitching_fee": "450.00",
                    "urgent_surcharge": "50.00",
                    "fabric_component": "0.00",
                },
                quotation_status="VALID",
                pricing_config_version="v1.0.0-mock",
                quotation_timestamp=now,
                valid_until=now + timedelta(days=14),
                customer_ref=None,
            ),
            "QUO-CAT-001": QuotationRecord(
                quotation_id="QUO-CAT-001",
                quoted_amount=Decimal("1250.00"),
                currency="INR",
                price_breakdown={
                    "stitching_fee": "450.00",
                    "fabric_component": "800.00",
                },
                quotation_status="VALID",
                pricing_config_version="v1.1.0-mock",
                quotation_timestamp=now,
                valid_until=now + timedelta(days=30),
                customer_ref=None,
            ),
            "QUO-EXPIRED": QuotationRecord(
                quotation_id="QUO-EXPIRED",
                quoted_amount=Decimal("450.00"),
                currency="INR",
                price_breakdown={"stitching_fee": "450.00"},
                quotation_status="VALID",
                pricing_config_version="v0.9.0-mock",
                quotation_timestamp=now - timedelta(days=60),
                valid_until=now - timedelta(days=1),
                customer_ref=None,
            ),
            "QUO-REVOKED": QuotationRecord(
                quotation_id="QUO-REVOKED",
                quoted_amount=Decimal("450.00"),
                currency="INR",
                price_breakdown={"stitching_fee": "450.00"},
                quotation_status="REVOKED",
                pricing_config_version="v1.0.0-mock",
                quotation_timestamp=now,
                valid_until=now + timedelta(days=7),
                customer_ref=None,
            ),
        }

    def set_failure_mode(self, fail: bool) -> None:
        self._simulate_failure = fail

    def register_quotation(self, record: QuotationRecord) -> None:
        self._quotations[record.quotation_id] = record

    def get_quotation(self, quotation_id: str) -> QuotationRecord | None:
        if self._simulate_failure:
            raise IntegrationError(
                "Module 05 Pricing Engine adapter unavailable (simulated failure)."
            )
        return self._quotations.get(quotation_id.strip())


class MockMeasurementAdapter:
    """Temporary replaceable Module 06 adapter backed by synthetic measurement profiles."""

    def __init__(self) -> None:
        now = datetime(2026, 11, 18, 8, 30, tzinfo=timezone.utc)
        self._simulate_failure: bool = False
        self._records: dict[str, MeasurementRecord] = {
            "MEA-001": MeasurementRecord(
                measurement_id="MEA-001",
                customer_ref="CUS-001",
                profile_version=1,
                validation_status="VALIDATED",
                approval_status="APPROVED",
                measurements={
                    "unit": "cm",
                    "chest": 100.0,
                    "waist": 86.0,
                    "shoulder": 45.0,
                    "sleeve_length": 62.0,
                    "shirt_length": 74.0,
                    "neck": 39.5,
                },
                recorded_at=now,
            ),
            "MEA-001-ALT": MeasurementRecord(
                measurement_id="MEA-001-ALT",
                customer_ref="CUS-001",
                profile_version=2,
                validation_status="VALIDATED",
                approval_status="APPROVED",
                measurements={
                    "unit": "cm",
                    "chest": 102.0,
                    "waist": 88.0,
                    "shoulder": 45.5,
                    "sleeve_length": 62.5,
                    "shirt_length": 75.0,
                    "neck": 40.0,
                },
                recorded_at=now,
            ),
            "MEA-002": MeasurementRecord(
                measurement_id="MEA-002",
                customer_ref="CUS-002",
                profile_version=1,
                validation_status="VALIDATED",
                approval_status="APPROVED",
                measurements={
                    "unit": "cm",
                    "chest": 104.0,
                    "waist": 90.0,
                    "shoulder": 46.5,
                    "sleeve_length": 63.5,
                    "shirt_length": 76.0,
                },
                recorded_at=now,
            ),
            "MEA-UNVALIDATED": MeasurementRecord(
                measurement_id="MEA-UNVALIDATED",
                customer_ref="CUS-001",
                profile_version=1,
                validation_status="UNVALIDATED",
                approval_status="PENDING",
                measurements={"unit": "cm", "chest": 98.0},
                recorded_at=now,
            ),
        }

    def set_failure_mode(self, fail: bool) -> None:
        self._simulate_failure = fail

    def register_measurement(self, record: MeasurementRecord) -> None:
        self._records[record.measurement_id] = record

    def get_measurement(self, measurement_id: str) -> MeasurementRecord | None:
        if self._simulate_failure:
            raise IntegrationError(
                "Module 06 Measurement Guide adapter unavailable (simulated failure)."
            )
        return self._records.get(measurement_id.strip())


class MockFabricCatalogAdapter:
    """Temporary replaceable Module 02 adapter aligned with `FAB-NNN` / `FVAR-NNN` draft contract."""

    def __init__(self) -> None:
        self._simulate_failure: bool = False
        self._fabrics: dict[str, FabricRecord] = {
            "FAB-001": FabricRecord(
                fabric_id="FAB-001",
                variant_id="FVAR-001",
                fabric_name="Synthetic Test Poplin",
                fabric_type="Poplin",
                sourcing_method=FabricSource.BUSINESS_INVENTORY.value,
                availability_status="AVAILABLE",
                colour_name="Classic White",
                colour_hex="#FFFFFF",
                attributes={"composition": "100% Cotton"},
            ),
            "FAB-002": FabricRecord(
                fabric_id="FAB-002",
                variant_id="FVAR-002",
                fabric_name="Synthetic Test Linen",
                fabric_type="Linen",
                sourcing_method=FabricSource.BUSINESS_INVENTORY.value,
                availability_status="ON_REQUEST",
                colour_name="Sky Blue",
                colour_hex="#87CEEB",
                attributes={"composition": "100% Linen"},
            ),
            "FAB-OUT": FabricRecord(
                fabric_id="FAB-OUT",
                variant_id="FVAR-OUT",
                fabric_name="Out of Stock Twill",
                fabric_type="Twill",
                sourcing_method=FabricSource.BUSINESS_INVENTORY.value,
                availability_status="OUT_OF_STOCK",
                colour_name="Navy",
                colour_hex="#001F3F",
            ),
        }

    def set_failure_mode(self, fail: bool) -> None:
        self._simulate_failure = fail

    def register_fabric(self, record: FabricRecord) -> None:
        self._fabrics[record.fabric_id] = record

    def get_fabric(
        self,
        fabric_id: str,
        *,
        variant_id: str | None = None,
        fabric_source: str = FabricSource.CUSTOMER_SUPPLIED.value,
    ) -> FabricRecord | None:
        if self._simulate_failure:
            raise IntegrationError(
                "Module 02 Fabric Catalog adapter unavailable (simulated failure)."
            )
        cleaned = fabric_id.strip()
        if not cleaned:
            return None

        if fabric_source == FabricSource.CUSTOMER_SUPPLIED.value:
            # Customers in Dhundhwana frequently supply their own cloth; record a
            # traceable customer-supplied reference without pretending it is catalogue stock.
            if cleaned in self._fabrics:
                cat = self._fabrics[cleaned]
                return FabricRecord(
                    fabric_id=cat.fabric_id,
                    variant_id=variant_id or cat.variant_id,
                    fabric_name=cat.fabric_name,
                    fabric_type=cat.fabric_type,
                    sourcing_method=FabricSource.CUSTOMER_SUPPLIED.value,
                    availability_status="CUSTOMER_PROVIDED",
                    colour_name=cat.colour_name,
                    colour_hex=cat.colour_hex,
                    attributes=cat.attributes,
                )
            return FabricRecord(
                fabric_id=cleaned,
                variant_id=variant_id,
                fabric_name="Customer-Supplied Fabric",
                fabric_type="Customer Provided",
                sourcing_method=FabricSource.CUSTOMER_SUPPLIED.value,
                availability_status="CUSTOMER_PROVIDED",
            )

        record = self._fabrics.get(cleaned)
        if record is None:
            return None
        if variant_id and record.variant_id and variant_id != record.variant_id:
            return None
        return record


class MockDesignConfigAdapter:
    """Temporary replaceable Module 03 adapter aligned with `DSG-...` draft schema v1.0.0."""

    def __init__(self) -> None:
        now = datetime(2026, 11, 18, 8, 0, tzinfo=timezone.utc)
        self._simulate_failure: bool = False
        self._designs: dict[str, DesignRecord] = {
            "DSG-001": DesignRecord(
                design_id="DSG-001",
                schema_version="1.0.0",
                garment_type="shirt",
                fabric_ref="FAB-001",
                components={
                    "collar": {"style": "classic"},
                    "sleeves": {"style": "full"},
                    "cuffs": {"style": "standard"},
                    "pockets": {"style": "single", "flap_style": "none"},
                    "buttons": {"style": "basic", "placement": "standard"},
                    "thread": {"color_hex": "#FFFFFF"},
                    "fit": {"type": "regular"},
                },
                created_at=now,
            ),
            "DSG-002": DesignRecord(
                design_id="DSG-002",
                schema_version="1.0.0",
                garment_type="shirt_and_pant_set",
                fabric_ref="CUST-FAB-001",
                components={
                    "collar": {"style": "mandarin"},
                    "sleeves": {"style": "full"},
                    "cuffs": {"style": "button"},
                    "pockets": {"style": "single", "flap_style": "standard"},
                    "buttons": {"style": "standard", "placement": "standard"},
                    "thread": {"color_hex": "#F5F5F5"},
                    "fit": {"type": "regular"},
                    "trouser_pleats": "flat_front",
                },
                created_at=now,
            ),
            "DSG-INVALID": DesignRecord(
                design_id="DSG-INVALID",
                schema_version="1.0.0",
                garment_type="shirt",
                components={"collar": {"style": "unsupported_collar"}},
                is_valid=False,
                created_at=now,
            ),
        }

    def set_failure_mode(self, fail: bool) -> None:
        self._simulate_failure = fail

    def register_design(self, record: DesignRecord) -> None:
        self._designs[record.design_id] = record

    def get_design(self, design_id: str) -> DesignRecord | None:
        if self._simulate_failure:
            raise IntegrationError(
                "Module 03 2D Clothing Designer adapter unavailable (simulated failure)."
            )
        return self._designs.get(design_id.strip())


class MockPreviewReferenceAdapter:
    """Temporary replaceable Module 04 3D preview reference adapter."""

    def __init__(self) -> None:
        self._simulate_failure: bool = False
        self._previews: dict[str, PreviewRecord] = {
            "PRV-001": PreviewRecord(
                preview_id="PRV-001",
                design_id="DSG-001",
                preview_url="https://preview.invalid/renders/PRV-001",
                metadata={"camera_view": "front"},
            )
        }

    def set_failure_mode(self, fail: bool) -> None:
        self._simulate_failure = fail

    def register_preview(self, record: PreviewRecord) -> None:
        self._previews[record.preview_id] = record

    def get_preview(self, preview_id: str) -> PreviewRecord | None:
        if self._simulate_failure:
            raise IntegrationError(
                "Module 04 3D Preview adapter unavailable (simulated failure)."
            )
        return self._previews.get(preview_id.strip())


class MockNotificationProvider:
    """In-memory mock notification provider — NEVER dispatches real external messages."""

    def __init__(self) -> None:
        self._simulate_failure: bool = False
        self.sent_messages: list[dict[str, Any]] = []

    def set_failure_mode(self, fail: bool) -> None:
        self._simulate_failure = fail

    def dispatch(
        self,
        *,
        notification_ref: str,
        event_type: str,
        channel: str,
        recipient_ref: str,
        payload: dict[str, Any],
    ) -> NotificationDispatchResult:
        if self._simulate_failure:
            return NotificationDispatchResult(
                delivered=False,
                provider_name="mock",
                status_label="FAILED",
                error_message="Simulated mock notification provider failure.",
            )
        self.sent_messages.append(
            {
                "notification_ref": notification_ref,
                "event_type": event_type,
                "channel": channel,
                "recipient_ref": recipient_ref,
                "payload": dict(payload),
            }
        )
        return NotificationDispatchResult(
            delivered=True,
            provider_name="mock",
            status_label="SENT_MOCK",
        )
