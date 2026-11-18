"""Order Lifecycle, History, Transitions, and Snapshots endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_principal,
    get_db,
    get_lifecycle_engine,
    get_order_service,
)
from app.api.serializers import (
    serialize_event,
    serialize_order,
    serialize_snapshot_detail,
    serialize_status,
)
from app.core.security import Principal
from app.schemas.lifecycle import (
    OrderEventResponse,
    OrderStatusResponse,
    StatusTransitionRequest,
)
from app.schemas.orders import OrderResponse, OrderSnapshotDetailResponse
from app.services.lifecycle_engine import STAFF_ROLES, LifecycleEngine
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["Lifecycle"])


@router.get("/{order_id}/status", response_model=OrderStatusResponse)
def get_order_status(
    order_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderStatusResponse:
    order = service.get_authorized_order(
        db, identifier=order_id, principal=principal
    )
    return serialize_status(order, principal=principal)


@router.get("/{order_id}/history", response_model=list[OrderEventResponse])
def get_order_history(
    order_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> list[OrderEventResponse]:
    order = service.get_authorized_order(
        db, identifier=order_id, principal=principal
    )
    is_staff = principal.role in STAFF_ROLES
    events = [
        ev for ev in order.events if is_staff or ev.customer_visible
    ]
    return [
        serialize_event(ev, order_ref=order.public_order_ref, principal=principal)
        for ev in events
    ]


@router.get("/{order_id}/snapshots", response_model=list[OrderSnapshotDetailResponse])
def get_order_snapshots(
    order_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> list[OrderSnapshotDetailResponse]:
    order = service.get_authorized_order(
        db, identifier=order_id, principal=principal
    )
    return [serialize_snapshot_detail(s, principal=principal) for s in order.snapshots]


@router.post("/{order_id}/transitions", response_model=OrderResponse)
def transition_order_status(
    order_id: str,
    payload: StatusTransitionRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
    lifecycle: LifecycleEngine = Depends(get_lifecycle_engine),
) -> OrderResponse:
    order = service.get_authorized_order(
        db, identifier=order_id, principal=principal
    )
    lifecycle.transition(
        db,
        order=order,
        target_status=payload.target_status,
        principal=principal,
        reason=payload.reason,
        expected_version=payload.expected_version,
        is_admin_correction=payload.is_admin_correction,
        metadata=payload.metadata,
    )
    db.commit()
    db.refresh(order)
    return serialize_order(order, principal=principal)
