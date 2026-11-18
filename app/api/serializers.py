"""Privacy-aware serializers converting ORM models into Pydantic responses."""

import math
from typing import Any, TypeVar

from app.core.enums import ActorRole, NoteVisibility, OrderStatus
from app.core.security import Principal
from app.models.entities import (
    NotificationEvent,
    Order,
    OrderEvent,
    OrderSnapshot,
    WorkflowTask,
)
from app.schemas.admin import NotificationEventResponse
from app.schemas.common import PaginatedResponse
from app.schemas.lifecycle import OrderEventResponse, OrderStatusResponse
from app.schemas.orders import (
    OrderItemResponse,
    OrderNoteResponse,
    OrderResponse,
    OrderSnapshotDetailResponse,
    OrderSnapshotSummaryResponse,
)
from app.schemas.workflow import WorkflowTaskResponse
from app.services.lifecycle_engine import CUSTOMER_VISIBLE_STATUS_LABELS, STAFF_ROLES

T = TypeVar("T")


def build_page(items: list[T], *, total: int, page: int, page_size: int) -> PaginatedResponse[T]:
    pages = max(1, math.ceil(total / page_size)) if total > 0 else 0
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


def serialize_order(
    order: Order,
    *,
    principal: Principal,
    tracking_token: str | None = None,
    idempotent_replay: bool = False,
) -> OrderResponse:
    is_staff = principal.role in STAFF_ROLES

    items = [
        OrderItemResponse(
            line_number=it.line_number,
            garment_type=it.garment_type,
            quantity=it.quantity,
            design_ref=it.design_ref,
            design_version=it.design_version,
            fabric_source=it.fabric_source,
            fabric_ref=it.fabric_ref,
            fabric_variant_ref=it.fabric_variant_ref,
            preview_3d_ref=it.preview_3d_ref,
            customization_data=dict(it.customization_data or {}),
            item_notes=it.item_notes,
        )
        for it in order.items
    ]

    # CRITICAL PRIVACY GUARD: Never expose INTERNAL notes to non-staff callers
    notes = [
        OrderNoteResponse(
            id=n.id,
            visibility=n.visibility,
            author_id=n.author_id if is_staff else None,
            author_role=n.author_role if is_staff else None,
            content=n.content,
            created_at=n.created_at,
        )
        for n in order.notes
        if is_staff or n.visibility == NoteVisibility.CUSTOMER_VISIBLE.value
    ]

    snapshots = [
        OrderSnapshotSummaryResponse(
            snapshot_version=s.snapshot_version,
            snapshot_type=s.snapshot_type,
            confirmed_amount=s.confirmed_amount,
            currency=s.currency,
            confirmed_by=s.confirmed_by if is_staff else "VERIFIED",
            confirmed_role=s.confirmed_role,
            created_at=s.created_at,
        )
        for s in order.snapshots
    ]

    status_enum = OrderStatus(order.current_status)
    return OrderResponse(
        id=order.id,
        order_reference=order.public_order_ref,
        customer_ref=order.customer_ref,
        current_status=order.current_status,
        customer_status_label=CUSTOMER_VISIBLE_STATUS_LABELS[status_enum],
        order_source=order.order_source,
        submission_reference=order.submission_reference,
        currency=order.currency,
        measurement_ref=order.measurement_ref,
        quotation_ref=order.quotation_ref,
        quoted_amount=order.quoted_amount,
        customer_price_confirmed=order.customer_price_confirmed,
        customer_confirmed_at=order.customer_confirmed_at,
        is_urgent=order.is_urgent,
        customer_instructions=order.customer_instructions,
        delivery_method=order.delivery_method,
        delivery_reference=order.delivery_reference,
        delivered_at=order.delivered_at,
        completed_at=order.completed_at,
        cancelled_at=order.cancelled_at,
        cancellation_reason=order.cancellation_reason,
        version=order.version,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=items,
        notes=notes,
        snapshots=snapshots,
        tracking_token=tracking_token,
        idempotent_replay=idempotent_replay,
    )


def serialize_status(order: Order, *, principal: Principal) -> OrderStatusResponse:
    is_staff = principal.role in STAFF_ROLES
    status_enum = OrderStatus(order.current_status)
    return OrderStatusResponse(
        order_reference=order.public_order_ref,
        current_status=order.current_status,
        customer_status_label=CUSTOMER_VISIBLE_STATUS_LABELS[status_enum],
        previous_hold_status=order.previous_hold_status if is_staff else None,
        hold_reason=order.hold_reason,
        latest_inspection_result=order.latest_inspection_result if is_staff else None,
        rework_count=order.rework_count if is_staff else 0,
        customer_price_confirmed=order.customer_price_confirmed,
        version=order.version,
        updated_at=order.updated_at,
    )


def serialize_event(
    event: OrderEvent, *, order_ref: str, principal: Principal
) -> OrderEventResponse:
    is_staff = principal.role in STAFF_ROLES
    return OrderEventResponse(
        event_ref=event.event_ref,
        order_reference=order_ref,
        event_type=event.event_type,
        previous_status=event.previous_status,
        new_status=event.new_status,
        actor_id=event.actor_id if is_staff else None,
        actor_role=event.actor_role if is_staff else None,
        reason=event.reason if is_staff else None,
        customer_visible=event.customer_visible,
        customer_message=event.customer_message,
        metadata=dict(event.metadata_json or {}) if is_staff else {},
        created_at=event.created_at,
    )


def serialize_snapshot_detail(
    snapshot: OrderSnapshot, *, principal: Principal
) -> OrderSnapshotDetailResponse:
    is_staff = principal.role in STAFF_ROLES
    measurement_data: dict[str, Any] = dict(snapshot.measurement_snapshot or {})
    if principal.role == ActorRole.CUSTOMER:
        # Customers may view their own measurement version metadata without raw API exposure
        measurement_data = {
            "measurement_id": measurement_data.get("measurement_id"),
            "profile_version": measurement_data.get("profile_version"),
            "validation_status": measurement_data.get("validation_status"),
            "approval_status": measurement_data.get("approval_status"),
            "recorded_at": measurement_data.get("recorded_at"),
        }
    return OrderSnapshotDetailResponse(
        snapshot_version=snapshot.snapshot_version,
        snapshot_type=snapshot.snapshot_type,
        confirmed_amount=snapshot.confirmed_amount,
        currency=snapshot.currency,
        confirmed_by=snapshot.confirmed_by if is_staff else "CUSTOMER_CONFIRMED",
        confirmed_role=snapshot.confirmed_role,
        created_at=snapshot.created_at,
        design_snapshot=dict(snapshot.design_snapshot or {}),
        fabric_snapshot=dict(snapshot.fabric_snapshot or {}),
        measurement_snapshot=measurement_data,
        quotation_snapshot=dict(snapshot.quotation_snapshot or {}),
    )


def serialize_task(task: WorkflowTask) -> WorkflowTaskResponse:
    return WorkflowTaskResponse(
        id=task.id,
        task_ref=task.task_ref,
        order_id=task.order_id,
        order_reference=task.order.public_order_ref,
        stage=task.stage,
        task_name=task.task_name,
        task_status=task.task_status,
        assigned_staff_ref=task.assigned_staff_ref,
        is_rework=task.is_rework,
        checklist=dict(task.checklist_json or {}),
        material_ready=task.material_ready,
        missing_material_info=task.missing_material_info,
        inspection_result=task.inspection_result,
        approved_corrections=task.approved_corrections,
        rework_requirements=task.rework_requirements,
        notes=task.notes,
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_by=task.created_by,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def serialize_notification(notif: NotificationEvent) -> NotificationEventResponse:
    return NotificationEventResponse(
        notification_ref=notif.notification_ref,
        order_reference=notif.order.public_order_ref,
        event_type=notif.event_type,
        channel=notif.channel,
        recipient_ref=notif.recipient_ref,
        payload=dict(notif.payload_json or {}),
        delivery_status=notif.delivery_status,
        provider_name=notif.provider_name,
        error_message=notif.error_message,
        created_at=notif.created_at,
        processed_at=notif.processed_at,
    )
