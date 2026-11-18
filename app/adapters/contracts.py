"""Typed adapter contracts for Modules 02, 03, 04, 05, 06, and Notification delivery.

IMPORTANT:
- Only Module 02 (`fabric-catalog-system`) and Module 03 (`-3-2D-CLOTHING-DESIGNER`)
  currently have draft contracts on unmerged development branches.
- Modules 01, 04, 05, 06, and 08 currently have no merged API contracts on `main`.
- All contracts below are clean, replaceable adapter boundaries so Module 07 never
  invents hardcoded upstream URLs or calculates prices independently.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol


@dataclass(frozen=True)
class QuotationRecord:
    """Module 05 (Clothing Price Engine) quotation representation."""

    quotation_id: str
    quoted_amount: Decimal
    currency: str
    price_breakdown: dict[str, Any]
    quotation_status: str  # e.g., "VALID", "EXPIRED", "REVOKED"
    pricing_config_version: str
    quotation_timestamp: datetime
    valid_until: datetime | None = None
    customer_ref: str | None = None

    def is_currently_valid(self, now: datetime | None = None) -> bool:
        check_time = now or datetime.now(timezone.utc)
        if self.quotation_status.upper() not in {"VALID", "APPROVED", "ACTIVE"}:
            return False
        if self.valid_until is not None:
            valid_until = (
                self.valid_until
                if self.valid_until.tzinfo is not None
                else self.valid_until.replace(tzinfo=timezone.utc)
            )
            if valid_until < check_time:
                return False
        return self.quoted_amount >= Decimal("0.00")

    def to_snapshot_dict(self) -> dict[str, Any]:
        return {
            "quotation_id": self.quotation_id,
            "quoted_amount": str(self.quoted_amount),
            "currency": self.currency,
            "price_breakdown": self.price_breakdown,
            "quotation_status": self.quotation_status,
            "pricing_config_version": self.pricing_config_version,
            "quotation_timestamp": self.quotation_timestamp.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
        }


@dataclass(frozen=True)
class MeasurementRecord:
    """Module 06 (Measurement Guide) measurement profile representation."""

    measurement_id: str
    customer_ref: str
    profile_version: int
    validation_status: str  # "VALIDATED", "UNVALIDATED", "INVALID"
    approval_status: str  # "APPROVED", "PENDING"
    measurements: dict[str, Any]
    recorded_at: datetime

    @property
    def is_verified(self) -> bool:
        return self.validation_status.upper() == "VALIDATED" and (
            self.approval_status.upper() in {"APPROVED", "VERIFIED"}
        )

    def to_snapshot_dict(self) -> dict[str, Any]:
        return {
            "measurement_id": self.measurement_id,
            "customer_ref": self.customer_ref,
            "profile_version": self.profile_version,
            "validation_status": self.validation_status,
            "approval_status": self.approval_status,
            "measurements": dict(self.measurements),
            "recorded_at": self.recorded_at.isoformat(),
        }


@dataclass(frozen=True)
class FabricRecord:
    """Module 02 (Fabric Catalog System) or customer-supplied fabric representation."""

    fabric_id: str
    fabric_name: str
    fabric_type: str
    sourcing_method: str  # "CUSTOMER_SUPPLIED" or "BUSINESS_INVENTORY"
    availability_status: str  # "AVAILABLE", "ON_REQUEST", "OUT_OF_STOCK", "CUSTOMER_PROVIDED"
    is_active: bool = True
    variant_id: str | None = None
    colour_name: str | None = None
    colour_hex: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def is_usable_for_order(self) -> bool:
        if not self.is_active:
            return False
        return self.availability_status.upper() in {
            "AVAILABLE",
            "ON_REQUEST",
            "CUSTOMER_PROVIDED",
        }

    def to_snapshot_dict(self) -> dict[str, Any]:
        return {
            "fabric_id": self.fabric_id,
            "variant_id": self.variant_id,
            "fabric_name": self.fabric_name,
            "fabric_type": self.fabric_type,
            "sourcing_method": self.sourcing_method,
            "availability_status": self.availability_status,
            "colour_name": self.colour_name,
            "colour_hex": self.colour_hex,
            "attributes": dict(self.attributes),
        }


@dataclass(frozen=True)
class DesignRecord:
    """Module 03 (2D Clothing Designer) design configuration representation."""

    design_id: str
    schema_version: str
    garment_type: str
    components: dict[str, Any]
    is_valid: bool = True
    fabric_ref: str | None = None
    created_at: datetime | None = None

    def to_snapshot_dict(self) -> dict[str, Any]:
        return {
            "design_id": self.design_id,
            "schema_version": self.schema_version,
            "garment_type": self.garment_type,
            "fabric_ref": self.fabric_ref,
            "components": dict(self.components),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


@dataclass(frozen=True)
class PreviewRecord:
    """Module 04 (3D Clothing Preview) optional visualization reference."""

    preview_id: str
    design_id: str | None
    preview_url: str | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_snapshot_dict(self) -> dict[str, Any]:
        return {
            "preview_id": self.preview_id,
            "design_id": self.design_id,
            "preview_url": self.preview_url,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class NotificationDispatchResult:
    """Outcome returned by a notification delivery provider."""

    delivered: bool
    provider_name: str
    status_label: str  # "SENT_MOCK", "FAILED", "SKIPPED"
    error_message: str | None = None


class PricingAdapter(Protocol):
    def get_quotation(self, quotation_id: str) -> QuotationRecord | None:
        ...


class MeasurementAdapter(Protocol):
    def get_measurement(self, measurement_id: str) -> MeasurementRecord | None:
        ...


class FabricCatalogAdapter(Protocol):
    def get_fabric(
        self,
        fabric_id: str,
        *,
        variant_id: str | None = None,
        fabric_source: str = "CUSTOMER_SUPPLIED",
    ) -> FabricRecord | None:
        ...


class DesignConfigAdapter(Protocol):
    def get_design(self, design_id: str) -> DesignRecord | None:
        ...


class PreviewReferenceAdapter(Protocol):
    def get_preview(self, preview_id: str) -> PreviewRecord | None:
        ...


class NotificationProvider(Protocol):
    def dispatch(
        self,
        *,
        notification_ref: str,
        event_type: str,
        channel: str,
        recipient_ref: str,
        payload: dict[str, Any],
    ) -> NotificationDispatchResult:
        ...
