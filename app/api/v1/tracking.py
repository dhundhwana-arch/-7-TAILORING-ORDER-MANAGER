"""Secure Customer Tracking endpoint (`/api/v1/tracking/{order_reference}`)."""

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_optional_principal, get_tracking_service
from app.core.security import Principal
from app.schemas.tracking import CustomerTrackingResponse
from app.services.tracking_service import TrackingService

router = APIRouter(prefix="/tracking", tags=["Tracking"])


@router.get("/{order_reference}", response_model=CustomerTrackingResponse)
def track_order(
    order_reference: str,
    tracking_token_query: str | None = Query(default=None, alias="tracking_token"),
    tracking_token_header: str | None = Header(default=None, alias="X-Tracking-Token"),
    db: Session = Depends(get_db),
    principal: Principal | None = Depends(get_optional_principal),
    service: TrackingService = Depends(get_tracking_service),
) -> CustomerTrackingResponse:
    effective_token = tracking_token_header or tracking_token_query
    data = service.get_tracking_view(
        db,
        order_reference=order_reference,
        principal=principal,
        tracking_token=effective_token,
    )
    return CustomerTrackingResponse(**data)
