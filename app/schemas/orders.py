"""Order, OrderItem, Note, and Snapshot Pydantic v2 schemas."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import FabricSource, NoteVisibility


class OrderItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    garment_type: str = Field(..., min_length=2, max_length=48, examples=["shirt"])
    quantity: int = Field(default=1, ge=1, le=100)
    design_ref: str = Field(..., min_length=2, max_length=64, examples=["DSG-001"])
    fabric_source: FabricSource = Field(default=FabricSource.CUSTOMER_SUPPLIED)
    fabric_ref: str = Field(..., min_length=2, max_length=64, examples=["FAB-001"])
    fabric_variant_ref: str | None = Field(default=None, max_length=64)
    preview_3d_ref: str | None = Field(default=None, max_length=64)
    customization_data: dict[str, Any] = Field(default_factory=dict)
    item_notes: str | None = Field(default=None, max_length=1000)


class OrderCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_reference: str | None = Field(default=None, max_length=64)
    customer_ref: str = Field(..., min_length=2, max_length=64, examples=["CUS-001"])
    measurement_ref: str = Field(..., min_length=2, max_length=64, examples=["MEA-001"])
    quotation_ref: str | None = Field(default=None, max_length=64, examples=["QUO-001"])
    currency: str = Field(default="INR", min_length=3, max_length=8)
    order_source: str = Field(default="MODULE_01_PLATFORM", max_length=64)
    submission_reference: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)
    customer_instructions: str | None = Field(default=None, max_length=2000)
    is_urgent: bool = Field(default=False)
    submit_immediately: bool = Field(default=False)
    items: list[OrderItemCreate] = Field(..., min_length=1, max_length=25)


class OrderPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quotation_ref: str | None = Field(default=None, max_length=64)
    measurement_ref: str | None = Field(default=None, max_length=64)
    customer_instructions: str | None = Field(default=None, max_length=2000)
    is_urgent: bool | None = None
    expected_version: int | None = Field(default=None, ge=1)


class OrderSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int | None = Field(default=None, ge=1)


class OrderConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted_quotation_ref: str = Field(..., min_length=2, max_length=64)
    customer_confirmation_evidence: str | None = Field(default=None, max_length=500)
    expected_version: int | None = Field(default=None, ge=1)


class OrderCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=3, max_length=1000)
    expected_version: int | None = Field(default=None, ge=1)


class OrderNoteCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visibility: NoteVisibility = Field(default=NoteVisibility.INTERNAL)
    content: str = Field(..., min_length=1, max_length=2000)


class OrderItemResponse(BaseModel):
    line_number: int
    garment_type: str
    quantity: int
    design_ref: str
    design_version: str | None
    fabric_source: str
    fabric_ref: str
    fabric_variant_ref: str | None
    preview_3d_ref: str | None
    customization_data: dict[str, Any]
    item_notes: str | None


class OrderNoteResponse(BaseModel):
    id: int
    visibility: str
    author_id: str | None = None
    author_role: str | None = None
    content: str
    created_at: datetime


class OrderSnapshotSummaryResponse(BaseModel):
    snapshot_version: int
    snapshot_type: str
    confirmed_amount: Decimal
    currency: str
    confirmed_by: str
    confirmed_role: str
    created_at: datetime


class OrderSnapshotDetailResponse(OrderSnapshotSummaryResponse):
    design_snapshot: dict[str, Any]
    fabric_snapshot: dict[str, Any]
    measurement_snapshot: dict[str, Any]
    quotation_snapshot: dict[str, Any]


class OrderResponse(BaseModel):
    id: int
    order_reference: str
    customer_ref: str
    current_status: str
    customer_status_label: str
    order_source: str
    submission_reference: str | None
    currency: str
    measurement_ref: str
    quotation_ref: str | None
    quoted_amount: Decimal | None
    customer_price_confirmed: bool
    customer_confirmed_at: datetime | None
    is_urgent: bool
    customer_instructions: str | None
    delivery_method: str | None
    delivery_reference: str | None
    delivered_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    cancellation_reason: str | None
    version: int
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]
    notes: list[OrderNoteResponse]
    snapshots: list[OrderSnapshotSummaryResponse]
    tracking_token: str | None = None
    idempotent_replay: bool = False
