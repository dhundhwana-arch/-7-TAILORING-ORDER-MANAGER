"""Order Creation, Validation, Submission, Confirmation, and Notes Service (Phases 03 & 05)."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.adapters.registry import AdapterRegistry
from app.core.config import Settings
from app.core.enums import (
    ActorRole,
    FabricSource,
    NoteVisibility,
    NotificationEventType,
    OrderStatus,
)
from app.core.exceptions import (
    ConcurrencyConflictError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.core.security import (
    Principal,
    generate_tracking_token,
    hash_tracking_token,
)
from app.models.entities import (
    Order,
    OrderEvent,
    OrderItem,
    OrderNote,
    utc_now,
)
from app.services.identifiers import generate_public_ref, validate_reference_id
from app.services.lifecycle_engine import (
    ADMIN_ROLES,
    CUSTOMER_VISIBLE_STATUS_LABELS,
    STAFF_ROLES,
    LifecycleEngine,
)
from app.services.notification_service import NotificationService
from app.services.snapshot_service import SnapshotService

SUPPORTED_CURRENCIES = {"INR", "USD", "EUR", "GBP"}
PRE_CONFIRMATION_MUTABLE_STATUSES = {
    OrderStatus.DRAFT.value,
    OrderStatus.SUBMITTED.value,
    OrderStatus.UNDER_REVIEW.value,
    OrderStatus.QUOTE_PENDING.value,
    OrderStatus.AWAITING_CUSTOMER_CONFIRMATION.value,
}


@dataclass
class OrderCreationResult:
    order: Order
    tracking_token: str | None
    idempotent_replay: bool


class OrderService:
    """Transactional service for tailoring order creation, queries, confirmation, and notes."""

    def __init__(
        self,
        *,
        settings: Settings,
        adapters: AdapterRegistry,
        lifecycle_engine: LifecycleEngine,
        snapshot_service: SnapshotService,
        notification_service: NotificationService,
    ) -> None:
        self._settings = settings
        self._adapters = adapters
        self._lifecycle = lifecycle_engine
        self._snapshots = snapshot_service
        self._notifications = notification_service

    def create_order(
        self,
        session: Session,
        *,
        principal: Principal,
        customer_ref: str,
        measurement_ref: str,
        items_payload: list[dict[str, Any]],
        currency: str = "INR",
        quotation_ref: str | None = None,
        order_reference: str | None = None,
        order_source: str = "MODULE_01_PLATFORM",
        submission_reference: str | None = None,
        idempotency_key: str | None = None,
        customer_instructions: str | None = None,
        is_urgent: bool = False,
        submit_immediately: bool = False,
    ) -> OrderCreationResult:
        if principal.role not in {
            ActorRole.CUSTOMER,
            ActorRole.ADMIN,
            ActorRole.OWNER,
            ActorRole.SYSTEM,
        }:
            raise ForbiddenError(
                f"Role '{principal.role.value}' is not authorized to create orders."
            )

        clean_customer = validate_reference_id(
            customer_ref, field_name="customer_ref", required=True
        )
        assert clean_customer is not None

        if principal.role == ActorRole.CUSTOMER and clean_customer != principal.actor_id:
            raise ForbiddenError(
                "Customers may only create orders for their own customer_ref."
            )

        clean_idempotency = validate_reference_id(
            idempotency_key, field_name="idempotency_key", required=False
        )
        clean_submission_ref = validate_reference_id(
            submission_reference, field_name="submission_reference", required=False
        )
        clean_source = (
            validate_reference_id(order_source, field_name="order_source", required=True)
            or "MODULE_01_PLATFORM"
        )

        # 1. Idempotent replay lookup BEFORE side effects
        if clean_idempotency:
            existing_idem = session.scalar(
                select(Order).where(
                    Order.customer_ref == clean_customer,
                    Order.idempotency_key == clean_idempotency,
                )
            )
            if existing_idem is not None:
                return OrderCreationResult(
                    order=existing_idem,
                    tracking_token=None,
                    idempotent_replay=True,
                )

        # 2. Duplicate submission_reference protection
        if clean_submission_ref:
            existing_sub = session.scalar(
                select(Order).where(
                    Order.order_source == clean_source,
                    Order.submission_reference == clean_submission_ref,
                )
            )
            if existing_sub is not None:
                raise ConflictError(
                    f"Duplicate submission_reference '{clean_submission_ref}' for source '{clean_source}'.",
                    error_code="DUPLICATE_SUBMISSION",
                    details={"existing_order_reference": existing_sub.public_order_ref},
                )

        # 3. Optional caller-supplied public order reference uniqueness check
        if order_reference is not None:
            public_ref = validate_reference_id(
                order_reference, field_name="order_reference", required=True
            )
            assert public_ref is not None
            if session.scalar(
                select(Order.id).where(Order.public_order_ref == public_ref)
            ):
                raise ConflictError(
                    f"Order reference '{public_ref}' already exists.",
                    error_code="DUPLICATE_ORDER_REFERENCE",
                )
        else:
            public_ref = generate_public_ref("ORD")

        clean_currency = currency.strip().upper()
        if clean_currency not in SUPPORTED_CURRENCIES:
            raise ValidationError(
                f"Unsupported currency '{currency}'. Supported: {sorted(SUPPORTED_CURRENCIES)}.",
                error_code="UNSUPPORTED_CURRENCY",
            )

        # Urgent flag requires explicit staff/admin authorization; customers cannot self-authorize urgency
        if is_urgent and principal.role not in ADMIN_ROLES:
            raise ForbiddenError(
                "Urgent production priority requires explicit ADMIN or OWNER authorization."
            )

        clean_measurement = validate_reference_id(
            measurement_ref, field_name="measurement_ref", required=True
        )
        assert clean_measurement is not None
        measurement_record = self._adapters.measurement.get_measurement(clean_measurement)
        if measurement_record is None:
            raise ValidationError(
                f"Measurement reference '{clean_measurement}' was not found in Module 06.",
                error_code="INVALID_MEASUREMENT_REFERENCE",
            )
        if measurement_record.customer_ref != clean_customer:
            raise ValidationError(
                "Measurement profile customer_ref does not match order customer_ref.",
                error_code="MEASUREMENT_CUSTOMER_MISMATCH",
            )

        clean_quotation = validate_reference_id(
            quotation_ref, field_name="quotation_ref", required=False
        )
        quoted_amount = None
        if clean_quotation:
            q_rec = self._adapters.pricing.get_quotation(clean_quotation)
            if q_rec is None:
                raise ValidationError(
                    f"Quotation reference '{clean_quotation}' was not found in Module 05.",
                    error_code="INVALID_QUOTATION_REFERENCE",
                )
            if not q_rec.is_currently_valid():
                raise ValidationError(
                    f"Quotation '{clean_quotation}' is expired or invalid.",
                    error_code="EXPIRED_OR_INVALID_QUOTATION",
                )
            if q_rec.currency.upper() != clean_currency:
                raise ValidationError(
                    f"Quotation currency '{q_rec.currency}' does not match order currency '{clean_currency}'.",
                    error_code="QUOTATION_CURRENCY_MISMATCH",
                )
            quoted_amount = q_rec.quoted_amount

        if not items_payload:
            raise ValidationError(
                "At least one garment item is required to create an order.",
                error_code="EMPTY_ORDER_ITEMS",
            )

        validated_items: list[OrderItem] = []
        for idx, raw_item in enumerate(items_payload, start=1):
            qty = raw_item.get("quantity", 1)
            if not isinstance(qty, int) or qty < 1 or qty > 100:
                raise ValidationError(
                    f"Item #{idx} quantity must be an integer between 1 and 100.",
                    error_code="INVALID_QUANTITY",
                )
            garment_type = str(raw_item.get("garment_type", "")).strip().lower()
            if not garment_type:
                raise ValidationError(
                    f"Item #{idx} garment_type is required.",
                    error_code="MISSING_GARMENT_TYPE",
                )

            d_ref = validate_reference_id(
                raw_item.get("design_ref"), field_name="design_ref", required=True
            )
            assert d_ref is not None
            design_rec = self._adapters.design.get_design(d_ref)
            if design_rec is None:
                raise ValidationError(
                    f"Design reference '{d_ref}' was not found in Module 03.",
                    error_code="INVALID_DESIGN_REFERENCE",
                )
            if not design_rec.is_valid:
                raise ValidationError(
                    f"Design configuration '{d_ref}' failed validation.",
                    error_code="INVALID_DESIGN_CONFIGURATION",
                )

            f_source_raw = str(
                raw_item.get("fabric_source") or FabricSource.CUSTOMER_SUPPLIED.value
            ).strip().upper()
            try:
                f_source = FabricSource(f_source_raw)
            except ValueError as exc:
                raise ValidationError(
                    f"Invalid fabric_source '{f_source_raw}'."
                ) from exc

            f_ref = validate_reference_id(
                raw_item.get("fabric_ref"), field_name="fabric_ref", required=True
            )
            assert f_ref is not None
            f_var_ref = validate_reference_id(
                raw_item.get("fabric_variant_ref"),
                field_name="fabric_variant_ref",
                required=False,
            )
            fabric_rec = self._adapters.fabric.get_fabric(
                f_ref, variant_id=f_var_ref, fabric_source=f_source.value
            )
            if fabric_rec is None:
                raise ValidationError(
                    f"Fabric reference '{f_ref}' was not found in Module 02.",
                    error_code="INVALID_FABRIC_REFERENCE",
                )
            if not fabric_rec.is_usable_for_order:
                raise ValidationError(
                    f"Fabric '{f_ref}' is currently unavailable ({fabric_rec.availability_status}).",
                    error_code="UNAVAILABLE_FABRIC",
                )

            prv_ref = validate_reference_id(
                raw_item.get("preview_3d_ref"),
                field_name="preview_3d_ref",
                required=False,
            )
            if prv_ref:
                if self._adapters.preview.get_preview(prv_ref) is None:
                    raise ValidationError(
                        f"3D Preview reference '{prv_ref}' was not found in Module 04.",
                        error_code="INVALID_PREVIEW_REFERENCE",
                    )

            customization_data = raw_item.get("customization_data") or {}
            if not isinstance(customization_data, dict):
                raise ValidationError("customization_data must be a JSON object.")

            validated_items.append(
                OrderItem(
                    line_number=idx,
                    garment_type=garment_type,
                    quantity=qty,
                    design_ref=d_ref,
                    design_version=design_rec.schema_version,
                    fabric_source=f_source.value,
                    fabric_ref=f_ref,
                    fabric_variant_ref=f_var_ref,
                    preview_3d_ref=prv_ref,
                    customization_data=customization_data,
                    item_notes=(raw_item.get("item_notes") or "").strip() or None,
                )
            )

        raw_tracking_token = generate_tracking_token()
        token_hash = hash_tracking_token(
            raw_tracking_token,
            order_ref=public_ref,
            secret_key=self._settings.TRACKING_TOKEN_SECRET,
        )

        # IMPORTANT: Never jump directly to CONFIRMED on creation/submission!
        initial_status = (
            OrderStatus.SUBMITTED if submit_immediately else OrderStatus.DRAFT
        )

        order = Order(
            public_order_ref=public_ref,
            customer_ref=clean_customer,
            current_status=initial_status.value,
            order_source=clean_source,
            submission_reference=clean_submission_ref,
            idempotency_key=clean_idempotency,
            currency=clean_currency,
            measurement_ref=clean_measurement,
            quotation_ref=clean_quotation,
            quoted_amount=quoted_amount,
            is_urgent=is_urgent,
            urgent_authorized_by=principal.actor_id if is_urgent else None,
            customer_instructions=(customer_instructions or "").strip() or None,
            tracking_token_hash=token_hash,
            version=1,
            created_at=utc_now(),
            updated_at=utc_now(),
            items=validated_items,
        )
        session.add(order)

        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            if clean_idempotency:
                existing = session.scalar(
                    select(Order).where(
                        Order.customer_ref == clean_customer,
                        Order.idempotency_key == clean_idempotency,
                    )
                )
                if existing is not None:
                    return OrderCreationResult(
                        order=existing,
                        tracking_token=None,
                        idempotent_replay=True,
                    )
            raise ConflictError(
                "Duplicate order creation or submission detected.",
                error_code="DUPLICATE_SUBMISSION",
            ) from exc

        creation_event = OrderEvent(
            event_ref=generate_public_ref("EVT"),
            order_id=order.id,
            event_type="ORDER_SUBMITTED" if submit_immediately else "ORDER_CREATED",
            previous_status=None,
            new_status=initial_status.value,
            actor_id=principal.actor_id,
            actor_role=principal.role.value,
            reason="Initial order submission" if submit_immediately else "Draft order created",
            customer_visible=True,
            customer_message=CUSTOMER_VISIBLE_STATUS_LABELS[initial_status],
            metadata_json={
                "order_source": clean_source,
                "item_count": len(validated_items),
            },
            created_at=utc_now(),
        )
        session.add(creation_event)
        session.flush()

        if submit_immediately:
            self._notifications.emit(
                session,
                order=order,
                event_type=NotificationEventType.ORDER_SUBMITTED,
                payload={"status": OrderStatus.SUBMITTED.value},
            )

        session.commit()
        session.refresh(order)
        return OrderCreationResult(
            order=order,
            tracking_token=raw_tracking_token,
            idempotent_replay=False,
        )

    def get_order_by_identifier(self, session: Session, identifier: str) -> Order:
        cleaned = identifier.strip()
        stmt = select(Order).where(Order.public_order_ref == cleaned)
        if cleaned.isdigit():
            stmt = select(Order).where(
                or_(Order.id == int(cleaned), Order.public_order_ref == cleaned)
            )
        order = session.scalar(stmt)
        if order is None:
            raise NotFoundError(f"Order '{cleaned}' was not found.")
        return order

    def get_authorized_order(
        self, session: Session, *, identifier: str, principal: Principal
    ) -> Order:
        order = self.get_order_by_identifier(session, identifier)
        if principal.role == ActorRole.CUSTOMER and order.customer_ref != principal.actor_id:
            raise ForbiddenError("Access denied: customers may only view their own orders.")
        return order

    def list_orders(
        self,
        session: Session,
        *,
        principal: Principal,
        status_filter: str | None = None,
        customer_ref_filter: str | None = None,
        search: str | None = None,
        is_urgent: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Order], int]:
        stmt = select(Order)
        count_stmt = select(func.count(Order.id))

        if principal.role == ActorRole.CUSTOMER:
            if customer_ref_filter and customer_ref_filter != principal.actor_id:
                raise ForbiddenError("Customers cannot query another customer's orders.")
            stmt = stmt.where(Order.customer_ref == principal.actor_id)
            count_stmt = count_stmt.where(Order.customer_ref == principal.actor_id)
        elif customer_ref_filter:
            stmt = stmt.where(Order.customer_ref == customer_ref_filter.strip())
            count_stmt = count_stmt.where(
                Order.customer_ref == customer_ref_filter.strip()
            )

        if status_filter:
            clean_st = status_filter.strip().upper()
            stmt = stmt.where(Order.current_status == clean_st)
            count_stmt = count_stmt.where(Order.current_status == clean_st)

        if is_urgent is not None:
            stmt = stmt.where(Order.is_urgent == is_urgent)
            count_stmt = count_stmt.where(Order.is_urgent == is_urgent)

        if search:
            term = f"%{search.strip()}%"
            cond = or_(
                Order.public_order_ref.ilike(term),
                Order.customer_ref.ilike(term),
                Order.submission_reference.ilike(term),
                Order.quotation_ref.ilike(term),
            )
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)

        total = int(session.scalar(count_stmt) or 0)
        offset = (page - 1) * page_size
        items = list(
            session.scalars(
                stmt.order_by(Order.created_at.desc(), Order.id.desc())
                .offset(offset)
                .limit(page_size)
            ).all()
        )
        return items, total

    def update_pre_confirmation_order(
        self,
        session: Session,
        *,
        identifier: str,
        principal: Principal,
        quotation_ref: str | None = None,
        measurement_ref: str | None = None,
        customer_instructions: str | None = None,
        is_urgent: bool | None = None,
        expected_version: int | None = None,
    ) -> Order:
        order = self.get_authorized_order(
            session, identifier=identifier, principal=principal
        )
        if expected_version is not None and order.version != expected_version:
            raise ConcurrencyConflictError(
                f"Order version conflict: expected {expected_version}, actual {order.version}."
            )

        # Once confirmed, silent mutation of price or measurement references is strictly forbidden!
        if order.current_status not in PRE_CONFIRMATION_MUTABLE_STATUSES:
            if quotation_ref is not None or measurement_ref is not None:
                raise ValidationError(
                    "Confirmed or active production orders cannot have their quotation_ref or "
                    "measurement_ref silently modified. Initiate explicit re-quotation/reconfirmation first.",
                    error_code="CONFIRMED_ORDER_PROTECTED",
                )

        changes: dict[str, Any] = {}

        if quotation_ref is not None:
            if principal.role not in STAFF_ROLES:
                raise ForbiddenError(
                    "Only authorized staff/admin may attach or update official quotation references."
                )
            clean_q = validate_reference_id(
                quotation_ref, field_name="quotation_ref", required=True
            )
            assert clean_q is not None
            q_rec = self._snapshots.verify_quotation(order, quotation_ref=clean_q)
            order.quotation_ref = clean_q
            order.quoted_amount = q_rec.quoted_amount
            order.customer_price_confirmed = False
            changes["quotation_ref"] = clean_q
            changes["quoted_amount"] = str(q_rec.quoted_amount)

        if measurement_ref is not None:
            clean_m = validate_reference_id(
                measurement_ref, field_name="measurement_ref", required=True
            )
            assert clean_m is not None
            m_rec = self._adapters.measurement.get_measurement(clean_m)
            if m_rec is None:
                raise ValidationError(
                    f"Measurement reference '{clean_m}' was not found in Module 06.",
                    error_code="INVALID_MEASUREMENT_REFERENCE",
                )
            if m_rec.customer_ref != order.customer_ref:
                raise ValidationError(
                    "Measurement profile belongs to a different customer.",
                    error_code="MEASUREMENT_CUSTOMER_MISMATCH",
                )
            order.measurement_ref = clean_m
            changes["measurement_ref"] = clean_m

        if customer_instructions is not None:
            order.customer_instructions = customer_instructions.strip() or None
            changes["customer_instructions_updated"] = True

        if is_urgent is not None:
            if principal.role not in ADMIN_ROLES:
                raise ForbiddenError(
                    "Only ADMIN or OWNER may modify urgent order authorization."
                )
            order.is_urgent = is_urgent
            order.urgent_authorized_by = principal.actor_id if is_urgent else None
            changes["is_urgent"] = is_urgent

        if not changes:
            return order

        order.updated_at = utc_now()
        session.add(
            OrderEvent(
                event_ref=generate_public_ref("EVT"),
                order_id=order.id,
                event_type="ORDER_DETAILS_UPDATED",
                previous_status=order.current_status,
                new_status=order.current_status,
                actor_id=principal.actor_id,
                actor_role=principal.role.value,
                reason="Order attributes updated",
                customer_visible=False,
                customer_message=None,
                metadata_json=changes,
                created_at=utc_now(),
            )
        )
        try:
            session.commit()
        except StaleDataError as exc:
            session.rollback()
            raise ConcurrencyConflictError(
                "Concurrent modification detected while updating order."
            ) from exc
        session.refresh(order)
        return order

    def submit_order(
        self,
        session: Session,
        *,
        identifier: str,
        principal: Principal,
        expected_version: int | None = None,
    ) -> Order:
        order = self.get_authorized_order(
            session, identifier=identifier, principal=principal
        )
        self._lifecycle.transition(
            session,
            order=order,
            target_status=OrderStatus.SUBMITTED,
            principal=principal,
            reason="Order submitted for tailoring review",
            expected_version=expected_version,
        )
        session.commit()
        session.refresh(order)
        return order

    def confirm_order(
        self,
        session: Session,
        *,
        identifier: str,
        principal: Principal,
        accepted_quotation_ref: str,
        customer_confirmation_evidence: str | None = None,
        expected_version: int | None = None,
    ) -> Order:
        order = self.get_authorized_order(
            session, identifier=identifier, principal=principal
        )
        clean_acc = validate_reference_id(
            accepted_quotation_ref,
            field_name="accepted_quotation_ref",
            required=True,
        )
        if not order.quotation_ref:
            raise ValidationError(
                "Order does not have an assigned quotation_ref yet.",
                error_code="MISSING_QUOTATION_REFERENCE",
            )
        if clean_acc != order.quotation_ref:
            raise ValidationError(
                f"accepted_quotation_ref '{clean_acc}' does not match active order quotation_ref '{order.quotation_ref}'.",
                error_code="QUOTATION_MISMATCH",
            )

        self._lifecycle.transition(
            session,
            order=order,
            target_status=OrderStatus.CONFIRMED,
            principal=principal,
            reason=f"Customer confirmed quotation {clean_acc}",
            expected_version=expected_version,
            metadata={
                "accepted_quotation_ref": clean_acc,
                "customer_confirmation_evidence": customer_confirmation_evidence,
            },
        )
        session.commit()
        session.refresh(order)
        return order

    def cancel_order(
        self,
        session: Session,
        *,
        identifier: str,
        principal: Principal,
        reason: str,
        expected_version: int | None = None,
    ) -> Order:
        order = self.get_authorized_order(
            session, identifier=identifier, principal=principal
        )
        self._lifecycle.transition(
            session,
            order=order,
            target_status=OrderStatus.CANCELLED,
            principal=principal,
            reason=reason,
            expected_version=expected_version,
        )
        session.commit()
        session.refresh(order)
        return order

    def add_note(
        self,
        session: Session,
        *,
        identifier: str,
        principal: Principal,
        content: str,
        visibility: NoteVisibility = NoteVisibility.INTERNAL,
    ) -> OrderNote:
        if principal.role not in STAFF_ROLES:
            raise ForbiddenError("Only workshop/admin staff may record order notes.")
        order = self.get_order_by_identifier(session, identifier)
        cleaned_content = content.strip()
        if not cleaned_content:
            raise ValidationError("Note content cannot be empty.")

        note = OrderNote(
            order_id=order.id,
            visibility=visibility.value,
            author_id=principal.actor_id,
            author_role=principal.role.value,
            content=cleaned_content,
            created_at=utc_now(),
        )
        session.add(note)
        session.add(
            OrderEvent(
                event_ref=generate_public_ref("EVT"),
                order_id=order.id,
                event_type=(
                    "CUSTOMER_NOTE_ADDED"
                    if visibility == NoteVisibility.CUSTOMER_VISIBLE
                    else "INTERNAL_NOTE_ADDED"
                ),
                previous_status=order.current_status,
                new_status=order.current_status,
                actor_id=principal.actor_id,
                actor_role=principal.role.value,
                reason="Note added",
                customer_visible=(visibility == NoteVisibility.CUSTOMER_VISIBLE),
                customer_message=(
                    cleaned_content
                    if visibility == NoteVisibility.CUSTOMER_VISIBLE
                    else None
                ),
                metadata_json={"visibility": visibility.value},
                created_at=utc_now(),
            )
        )
        session.commit()
        session.refresh(note)
        return note
