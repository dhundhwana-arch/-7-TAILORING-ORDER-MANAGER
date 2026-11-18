"""Capacity settings and workload summary schemas."""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class CapacitySettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sewing_machines_count: int | None = Field(default=None, ge=0, le=500)
    available_sewing_machines: int | None = Field(default=None, ge=0, le=500)
    overlock_machines_count: int | None = Field(default=None, ge=0, le=500)
    available_overlock_machines: int | None = Field(default=None, ge=0, le=500)
    irons_count: int | None = Field(default=None, ge=0, le=500)
    available_irons: int | None = Field(default=None, ge=0, le=500)
    cutting_tables_count: int | None = Field(default=None, ge=0, le=500)
    available_cutting_tables: int | None = Field(default=None, ge=0, le=500)
    reference_sets_per_day: Decimal | None = Field(default=None)
    max_active_production_orders_warning: int | None = Field(default=None, ge=1, le=5000)
    max_stage_orders_warning: int | None = Field(default=None, ge=1, le=5000)
    max_urgent_orders_warning: int | None = Field(default=None, ge=0, le=5000)
    operating_notes: str | None = Field(default=None, max_length=2000)
