"""Administrator & Module 08 Dashboard integration endpoints (`/api/v1/admin`)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_db, get_order_service
from app.api.serializers import (
    build_page,
    serialize_event,
    serialize_notification,
    serialize_order,
    serialize_snapshot_detail,
    serialize_task,
)
from app.core.security import Principal, ensure_roles
from app.models.entities import NotificationEvent, Order, OrderEvent
from app.schemas.admin import AdminOrderDetailResponse, NotificationEventResponse
from app.schemas.common import PaginatedResponse
from app.schemas.lifecycle import OrderEventResponse
from app.schemas.orders import OrderResponse
from app.services.lifecycle_engine import ADMIN_ROLES
from app.services.order_service import OrderService

router = APIRouter(prefix="/admin", tags=["Administration (Module 08 Contract)"])


@router.get("/orders", response_model=PaginatedResponse[OrderResponse])
def admin_list_orders(
    status_filter: str | None = Query(default=None, alias="status"),
    customer_ref: str | None = Query(default=None),
    search: str | None = Query(default=None),
    is_urgent: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> PaginatedResponse[OrderResponse]:
    ensure_roles(principal, ADMIN_ROLES)
    orders, total = service.list_orders(
        db,
        principal=principal,
        status_filter=status_filter,
        customer_ref_filter=customer_ref,
        search=search,
        is_urgent=is_urgent,
        page=page,
        page_size=page_size,
    )
    return build_page(
        [serialize_order(o, principal=principal) for o in orders],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/orders/{order_id}", response_model=AdminOrderDetailResponse)
def admin_get_order_detail(
    order_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> AdminOrderDetailResponse:
    ensure_roles(principal, ADMIN_ROLES)
    order = service.get_order_by_identifier(db, order_id)
    return AdminOrderDetailResponse(
        order=serialize_order(order, principal=principal),
        full_snapshots=[
            serialize_snapshot_detail(s, principal=principal) for s in order.snapshots
        ],
        workflow_tasks=[serialize_task(t) for t in order.workflow_tasks],
        audit_events=[
            serialize_event(
                ev, order_ref=order.public_order_ref, principal=principal
            )
            for ev in order.events
        ],
        notifications=[serialize_notification(n) for n in order.notifications],
    )


@router.get("/audit", response_model=PaginatedResponse[OrderEventResponse])
def admin_list_audit_events(
    order_reference: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    actor_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> PaginatedResponse[OrderEventResponse]:
    ensure_roles(principal, ADMIN_ROLES)
    stmt = select(OrderEvent).join(Order, OrderEvent.order_id == Order.id)
    count_stmt = select(func.count(OrderEvent.id)).join(
        Order, OrderEvent.order_id == Order.id
    )

    if order_reference:
        stmt = stmt.where(Order.public_order_ref == order_reference.strip())
        count_stmt = count_stmt.where(Order.public_order_ref == order_reference.strip())
    if event_type:
        stmt = stmt.where(OrderEvent.event_type == event_type.strip().upper())
        count_stmt = count_stmt.where(
            OrderEvent.event_type == event_type.strip().upper()
        )
    if actor_id:
        stmt = stmt.where(OrderEvent.actor_id == actor_id.strip())
        count_stmt = count_stmt.where(OrderEvent.actor_id == actor_id.strip())

    total = int(db.scalar(count_stmt) or 0)
    offset = (page - 1) * page_size
    events = list(
        db.scalars(
            stmt.order_by(OrderEvent.id.desc()).offset(offset).limit(page_size)
        ).all()
    )
    return build_page(
        [
            serialize_event(
                ev, order_ref=ev.order.public_order_ref, principal=principal
            )
            for ev in events
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/notifications", response_model=PaginatedResponse[NotificationEventResponse]
)
def admin_list_notifications(
    order_reference: str | None = Query(default=None),
    delivery_status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
) -> PaginatedResponse[NotificationEventResponse]:
    ensure_roles(principal, ADMIN_ROLES)
    stmt = select(NotificationEvent).join(Order, NotificationEvent.order_id == Order.id)
    count_stmt = select(func.count(NotificationEvent.id)).join(
        Order, NotificationEvent.order_id == Order.id
    )

    if order_reference:
        stmt = stmt.where(Order.public_order_ref == order_reference.strip())
        count_stmt = count_stmt.where(Order.public_order_ref == order_reference.strip())
    if delivery_status:
        stmt = stmt.where(
            NotificationEvent.delivery_status == delivery_status.strip().upper()
        )
        count_stmt = count_stmt.where(
            NotificationEvent.delivery_status == delivery_status.strip().upper()
        )

    total = int(db.scalar(count_stmt) or 0)
    offset = (page - 1) * page_size
    records = list(
        db.scalars(
            stmt.order_by(NotificationEvent.id.desc()).offset(offset).limit(page_size)
        ).all()
    )
    return build_page(
        [serialize_notification(n) for n in records],
        total=total,
        page=page,
        page_size=page_size,
    )
