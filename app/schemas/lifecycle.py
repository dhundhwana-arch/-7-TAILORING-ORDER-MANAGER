"""Lifecycle status, transition, and audit event schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import OrderStatus


class StatusTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_status: OrderStatus
    reason: str | None = Field(default=None, max_length=1000)
    expected_version: int | None = Field(default=None, ge=1)
    is_admin_correction: bool = Field(default=False)
    metadata: dict[str, Any] = Field(default_factory=dict)


class OrderStatusResponse(BaseModel):
    order_reference: str
    current_status: str
    customer_status_label: str
    previous_hold_status: str | None = None
    hold_reason: str | None = None
    latest_inspection_result: str | None = None
    rework_count: int
    customer_price_confirmed: bool
    version: int
    updated_at: datetime


class OrderEventResponse(BaseModel):
    event_ref: str
    order_reference: str
    event_type: str
    previous_status: str | None
    new_status: str | None
    actor_id: str | None = None
    actor_role: str | None = None
    reason: str | None = None
    customer_visible: bool
    customer_message: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
