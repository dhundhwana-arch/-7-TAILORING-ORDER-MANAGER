"""Customer-facing tracking response schemas."""

from datetime import datetime

from pydantic import BaseModel


class TrackingTimelineItem(BaseModel):
    event_type: str
    status: str | None
    status_label: str | None
    message: str
    timestamp: datetime


class TrackingCustomerUpdate(BaseModel):
    message: str
    timestamp: datetime


class TrackingDeliveryInfo(BaseModel):
    delivery_method: str
    delivery_reference: str
    delivered_at: datetime


class CustomerTrackingResponse(BaseModel):
    order_reference: str
    current_status: str
    customer_status_label: str
    created_at: datetime
    updated_at: datetime
    latest_update: str | None
    completed_stages: list[str]
    pending_stages: list[str]
    delivery_info: TrackingDeliveryInfo | None
    customer_instructions: str | None
    customer_updates: list[TrackingCustomerUpdate]
    timeline: list[TrackingTimelineItem]
