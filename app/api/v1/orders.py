"""Orders REST endpoints (`/api/v1/orders`)."""

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_principal, get_db, get_order_service
from app.api.serializers import build_page, serialize_order
from app.core.security import Principal
from app.schemas.common import PaginatedResponse
from app.schemas.orders import (
    OrderCancelRequest,
    OrderConfirmRequest,
    OrderCreateRequest,
    OrderNoteCreateRequest,
    OrderNoteResponse,
    OrderPatchRequest,
    OrderResponse,
    OrderSubmitRequest,
)
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreateRequest,
    response: Response,
    idempotency_key_header: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    effective_idem = idempotency_key_header or payload.idempotency_key
    result = service.create_order(
        db,
        principal=principal,
        customer_ref=payload.customer_ref,
        measurement_ref=payload.measurement_ref,
        quotation_ref=payload.quotation_ref,
        currency=payload.currency,
        order_reference=payload.order_reference,
        order_source=payload.order_source,
        submission_reference=payload.submission_reference,
        idempotency_key=effective_idem,
        customer_instructions=payload.customer_instructions,
        is_urgent=payload.is_urgent,
        submit_immediately=payload.submit_immediately,
        items_payload=[item.model_dump() for item in payload.items],
    )
    if result.idempotent_replay:
        response.status_code = status.HTTP_200_OK
    return serialize_order(
        result.order,
        principal=principal,
        tracking_token=result.tracking_token,
        idempotent_replay=result.idempotent_replay,
    )


@router.get("", response_model=PaginatedResponse[OrderResponse])
def list_orders(
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


@router.get("/{order_id}", response_model=OrderResponse)
def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    order = service.get_authorized_order(
        db, identifier=order_id, principal=principal
    )
    return serialize_order(order, principal=principal)


@router.patch("/{order_id}", response_model=OrderResponse)
def patch_order(
    order_id: str,
    payload: OrderPatchRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    order = service.update_pre_confirmation_order(
        db,
        identifier=order_id,
        principal=principal,
        quotation_ref=payload.quotation_ref,
        measurement_ref=payload.measurement_ref,
        customer_instructions=payload.customer_instructions,
        is_urgent=payload.is_urgent,
        expected_version=payload.expected_version,
    )
    return serialize_order(order, principal=principal)


@router.post("/{order_id}/submit", response_model=OrderResponse)
def submit_order(
    order_id: str,
    payload: OrderSubmitRequest | None = None,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    order = service.submit_order(
        db,
        identifier=order_id,
        principal=principal,
        expected_version=payload.expected_version if payload else None,
    )
    return serialize_order(order, principal=principal)


@router.post("/{order_id}/confirm", response_model=OrderResponse)
def confirm_order(
    order_id: str,
    payload: OrderConfirmRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    order = service.confirm_order(
        db,
        identifier=order_id,
        principal=principal,
        accepted_quotation_ref=payload.accepted_quotation_ref,
        customer_confirmation_evidence=payload.customer_confirmation_evidence,
        expected_version=payload.expected_version,
    )
    return serialize_order(order, principal=principal)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
def cancel_order(
    order_id: str,
    payload: OrderCancelRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderResponse:
    order = service.cancel_order(
        db,
        identifier=order_id,
        principal=principal,
        reason=payload.reason,
        expected_version=payload.expected_version,
    )
    return serialize_order(order, principal=principal)


@router.post(
    "/{order_id}/notes",
    response_model=OrderNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_order_note(
    order_id: str,
    payload: OrderNoteCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: OrderService = Depends(get_order_service),
) -> OrderNoteResponse:
    note = service.add_note(
        db,
        identifier=order_id,
        principal=principal,
        content=payload.content,
        visibility=payload.visibility,
    )
    return OrderNoteResponse(
        id=note.id,
        visibility=note.visibility,
        author_id=note.author_id,
        author_role=note.author_role,
        content=note.content,
        created_at=note.created_at,
    )
