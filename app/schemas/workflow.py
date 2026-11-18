"""Tailoring workflow task, inspection, delivery, and completion schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import InspectionResult, TaskStatus, WorkflowStage


class WorkflowTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_reference: str = Field(..., min_length=1, max_length=64)
    stage: WorkflowStage
    task_name: str = Field(..., min_length=2, max_length=120)
    assigned_staff_ref: str | None = Field(default=None, max_length=64)
    checklist: dict[str, bool] | None = None
    material_ready: bool | None = None
    missing_material_info: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class WorkflowTaskUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_status: TaskStatus | None = None
    assigned_staff_ref: str | None = Field(default=None, max_length=64)
    checklist_updates: dict[str, bool] | None = None
    material_ready: bool | None = None
    missing_material_info: str | None = Field(default=None, max_length=1000)
    inspection_result: InspectionResult | None = None
    approved_corrections: str | None = Field(default=None, max_length=1000)
    rework_requirements: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


class WorkflowTaskResponse(BaseModel):
    id: int
    task_ref: str
    order_id: int
    order_reference: str
    stage: str
    task_name: str
    task_status: str
    assigned_staff_ref: str | None
    is_rework: bool
    checklist: dict[str, Any]
    material_ready: bool | None
    missing_material_info: str | None
    inspection_result: str | None
    approved_corrections: str | None
    rework_requirements: str | None
    notes: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class RecordDeliveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_method: str = Field(..., min_length=2, max_length=32, examples=["COLLECTION"])
    delivery_reference: str = Field(..., min_length=2, max_length=128)
    delivery_recipient_ack: str | None = Field(default=None, max_length=500)
    expected_version: int | None = Field(default=None, ge=1)


class CompleteOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    completion_evidence: str = Field(..., min_length=5, max_length=1000)
    expected_version: int | None = Field(default=None, ge=1)
