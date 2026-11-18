"""Confirmation snapshot creation and cross-module verification service.

STRICT RULES (Sections 11, 12, 13, 22, 31):
1. Module 07 never calculates official prices independently; it consumes and
   verifies Module 05 quotations.
2. Confirmed snapshots are append-only and versioned (`snapshot_version = 1, 2, ...`).
3. Later changes to Module 05 pricing configs or Module 06 customer measurement
   profiles never mutate an existing confirmed `OrderSnapshot`.
"""

from copy import deepcopy
from typing import Any

from sqlalchemy.orm import Session

from app.adapters.contracts import QuotationRecord
from app.adapters.registry import AdapterRegistry
from app.core.enums import SnapshotType
from app.core.exceptions import ValidationError
from app.core.security import Principal
from app.models.entities import Order, OrderSnapshot, utc_now


class SnapshotService:
    """Verifies upstream references and persists immutable confirmation snapshots."""

    def __init__(self, adapters: AdapterRegistry) -> None:
        self._adapters = adapters

    def verify_quotation(self, order: Order, quotation_ref: str | None = None) -> QuotationRecord:
        q_ref = (quotation_ref or order.quotation_ref or "").strip()
        if not q_ref:
            raise ValidationError(
                "A valid Module 05 quotation_ref is required before price confirmation.",
                error_code="MISSING_QUOTATION_REFERENCE",
            )
        quotation = self._adapters.pricing.get_quotation(q_ref)
        if quotation is None:
            raise ValidationError(
                f"Quotation '{q_ref}' was not found in Module 05 Pricing Engine.",
                error_code="INVALID_QUOTATION_REFERENCE",
            )
        if not quotation.is_currently_valid():
            raise ValidationError(
                f"Quotation '{q_ref}' is expired or no longer valid (status={quotation.quotation_status}). "
                "Request an explicit re-quotation before confirming.",
                error_code="EXPIRED_OR_INVALID_QUOTATION",
            )
        if quotation.currency.upper() != order.currency.upper():
            raise ValidationError(
                f"Quotation currency '{quotation.currency}' does not match order currency '{order.currency}'.",
                error_code="QUOTATION_CURRENCY_MISMATCH",
            )
        if quotation.customer_ref and quotation.customer_ref != order.customer_ref:
            raise ValidationError(
                "Quotation customer_ref does not match order customer_ref.",
                error_code="QUOTATION_CUSTOMER_MISMATCH",
            )
        return quotation

    def create_confirmation_snapshot(
        self,
        session: Session,
        *,
        order: Order,
        principal: Principal,
        snapshot_type: SnapshotType = SnapshotType.ORDER_CONFIRMATION,
    ) -> OrderSnapshot:
        if not order.items:
            raise ValidationError("Order must contain at least one garment item.")

        quotation = self.verify_quotation(order)

        measurement = self._adapters.measurement.get_measurement(order.measurement_ref)
        if measurement is None:
            raise ValidationError(
                f"Measurement profile '{order.measurement_ref}' was not found in Module 06.",
                error_code="INVALID_MEASUREMENT_REFERENCE",
            )
        if measurement.customer_ref != order.customer_ref:
            raise ValidationError(
                "Measurement profile belongs to a different customer.",
                error_code="MEASUREMENT_CUSTOMER_MISMATCH",
            )
        if not measurement.is_verified:
            raise ValidationError(
                f"Measurement profile '{order.measurement_ref}' is not validated/approved "
                f"(validation_status={measurement.validation_status}, approval_status={measurement.approval_status}).",
                error_code="UNVALIDATED_MEASUREMENT_PROFILE",
            )

        design_items: list[dict[str, Any]] = []
        fabric_items: list[dict[str, Any]] = []

        for item in order.items:
            design = self._adapters.design.get_design(item.design_ref)
            if design is None:
                raise ValidationError(
                    f"Design reference '{item.design_ref}' was not found in Module 03.",
                    error_code="INVALID_DESIGN_REFERENCE",
                )
            if not design.is_valid:
                raise ValidationError(
                    f"Design configuration '{item.design_ref}' failed Module 03 validation.",
                    error_code="INVALID_DESIGN_CONFIGURATION",
                )

            fabric = self._adapters.fabric.get_fabric(
                item.fabric_ref,
                variant_id=item.fabric_variant_ref,
                fabric_source=item.fabric_source,
            )
            if fabric is None:
                raise ValidationError(
                    f"Fabric reference '{item.fabric_ref}' was not found in Module 02.",
                    error_code="INVALID_FABRIC_REFERENCE",
                )
            if not fabric.is_usable_for_order:
                raise ValidationError(
                    f"Fabric '{item.fabric_ref}' is unavailable (status={fabric.availability_status}).",
                    error_code="UNAVAILABLE_FABRIC",
                )

            preview_snapshot: dict[str, Any] | None = None
            if item.preview_3d_ref:
                preview = self._adapters.preview.get_preview(item.preview_3d_ref)
                if preview is None:
                    raise ValidationError(
                        f"3D Preview reference '{item.preview_3d_ref}' was not found in Module 04.",
                        error_code="INVALID_PREVIEW_REFERENCE",
                    )
                preview_snapshot = preview.to_snapshot_dict()

            design_items.append(
                {
                    "line_number": item.line_number,
                    "garment_type": item.garment_type,
                    "quantity": item.quantity,
                    "design": deepcopy(design.to_snapshot_dict()),
                    "order_customization_overrides": deepcopy(item.customization_data),
                    "preview_3d": preview_snapshot,
                }
            )
            fabric_items.append(
                {
                    "line_number": item.line_number,
                    "fabric_source": item.fabric_source,
                    "fabric": deepcopy(fabric.to_snapshot_dict()),
                }
            )

        next_version = len(order.snapshots) + 1
        snapshot = OrderSnapshot(
            order_id=order.id,
            snapshot_version=next_version,
            snapshot_type=snapshot_type.value,
            design_snapshot={"items": design_items},
            fabric_snapshot={"items": fabric_items},
            measurement_snapshot=deepcopy(measurement.to_snapshot_dict()),
            quotation_snapshot=deepcopy(quotation.to_snapshot_dict()),
            confirmed_amount=quotation.quoted_amount,
            currency=quotation.currency,
            confirmed_by=principal.actor_id,
            confirmed_role=principal.role.value,
            created_at=utc_now(),
        )
        session.add(snapshot)
        order.quoted_amount = quotation.quoted_amount
        session.flush()
        return snapshot
