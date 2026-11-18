"""Administrator detail and notification outbox response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.lifecycle import OrderEventResponse
from app.schemas.orders import OrderResponse, OrderSnapshotDetailResponse
from app.schemas.workflow import WorkflowTaskResponse


class NotificationEventResponse(BaseModel):
    notification_ref: str
    order_reference: str
    event_type: str
    channel: str
    recipient_ref: str
    payload: dict[str, Any]
    delivery_status: str
    provider_name: str
    error_message: str | None
    created_at: datetime
    processed_at: datetime | None


class AdminOrderDetailResponse(BaseModel):
    order: OrderResponse
    full_snapshots: list[OrderSnapshotDetailResponse]
    workflow_tasks: list[WorkflowTaskResponse]
    audit_events: list[OrderEventResponse]
    notifications: list[NotificationEventResponse]
