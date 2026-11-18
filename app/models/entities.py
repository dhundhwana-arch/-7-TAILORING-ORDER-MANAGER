"""SQLAlchemy 2.0 relational entities for Module 07 (Tailoring Order Manager).

Implements:
- Atomic optimistic locking (`Order.version` via SQLAlchemy `version_id_col`)
- Immutable append-only confirmed snapshots (`OrderSnapshot`)
- Immutable append-only audit trail (`OrderEvent`)
- Foreign keys with ON DELETE RESTRICT to protect historical order records
- Exact decimal representation (`Numeric(12, 2)`) for monetary figures
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    FabricSource,
    NoteVisibility,
    NotificationDeliveryStatus,
    OrderStatus,
    SnapshotType,
    TaskStatus,
)
from app.core.exceptions import ImmutableRecordError
from app.db.session import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Order(Base):
    """Core tailoring order lifecycle aggregate root."""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    public_order_ref: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    customer_ref: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    current_status: Mapped[str] = mapped_column(
        String(40), nullable=False, default=OrderStatus.DRAFT.value, index=True
    )
    previous_hold_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hold_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    order_source: Mapped[str] = mapped_column(
        String(64), nullable=False, default="MODULE_01_PLATFORM"
    )
    submission_reference: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    measurement_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    quotation_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    quoted_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    customer_price_confirmed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    customer_confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    customer_confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_urgent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, index=True
    )
    urgent_authorized_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    customer_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    tracking_token_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    # Quality inspection & delivery/completion evidence
    latest_inspection_result: Mapped[str | None] = mapped_column(
        String(48), nullable=True
    )
    rework_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    delivery_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delivery_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    delivery_recipient_ack: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    completion_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    items: Mapped[list["OrderItem"]] = relationship(
        "OrderItem",
        back_populates="order",
        order_by="OrderItem.line_number.asc()",
        cascade="save-update, merge",
    )
    snapshots: Mapped[list["OrderSnapshot"]] = relationship(
        "OrderSnapshot",
        back_populates="order",
        order_by="OrderSnapshot.snapshot_version.asc()",
        cascade="save-update, merge",
    )
    events: Mapped[list["OrderEvent"]] = relationship(
        "OrderEvent",
        back_populates="order",
        order_by="OrderEvent.id.asc()",
        cascade="save-update, merge",
    )
    workflow_tasks: Mapped[list["WorkflowTask"]] = relationship(
        "WorkflowTask",
        back_populates="order",
        order_by="WorkflowTask.id.asc()",
        cascade="save-update, merge",
    )
    notes: Mapped[list["OrderNote"]] = relationship(
        "OrderNote",
        back_populates="order",
        order_by="OrderNote.id.asc()",
        cascade="save-update, merge",
    )
    notifications: Mapped[list["NotificationEvent"]] = relationship(
        "NotificationEvent",
        back_populates="order",
        order_by="NotificationEvent.id.asc()",
        cascade="save-update, merge",
    )

    __mapper_args__ = {"version_id_col": version}

    __table_args__ = (
        UniqueConstraint(
            "customer_ref", "idempotency_key", name="uq_orders_customer_idempotency"
        ),
        UniqueConstraint(
            "order_source",
            "submission_reference",
            name="uq_orders_source_submission_ref",
        ),
        CheckConstraint("version >= 1", name="ck_orders_version_positive"),
        CheckConstraint("rework_count >= 0", name="ck_orders_rework_non_negative"),
        Index("ix_orders_status_created", "current_status", "created_at"),
    )


class OrderItem(Base):
    """One or more customized garments within an order."""

    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    garment_type: Mapped[str] = mapped_column(String(48), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    design_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    design_version: Mapped[str | None] = mapped_column(String(32), nullable=True)

    fabric_source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=FabricSource.CUSTOMER_SUPPLIED.value
    )
    fabric_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    fabric_variant_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)

    preview_3d_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    customization_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    item_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    order: Mapped["Order"] = relationship("Order", back_populates="items")

    __table_args__ = (
        UniqueConstraint("order_id", "line_number", name="uq_order_items_line"),
        CheckConstraint("quantity >= 1", name="ck_order_items_quantity_positive"),
        CheckConstraint("line_number >= 1", name="ck_order_items_line_positive"),
    )


class OrderSnapshot(Base):
    """Immutable versioned record preserving confirmed quotation, measurement, design, and fabric."""

    __tablename__ = "order_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    snapshot_version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_type: Mapped[str] = mapped_column(
        String(40), nullable=False, default=SnapshotType.ORDER_CONFIRMATION.value
    )

    design_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    fabric_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    measurement_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    quotation_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    confirmed_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="INR")
    confirmed_by: Mapped[str] = mapped_column(String(64), nullable=False)
    confirmed_role: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    order: Mapped["Order"] = relationship("Order", back_populates="snapshots")

    __table_args__ = (
        UniqueConstraint(
            "order_id", "snapshot_version", name="uq_order_snapshots_version"
        ),
        CheckConstraint(
            "snapshot_version >= 1", name="ck_order_snapshots_version_positive"
        ),
        CheckConstraint(
            "confirmed_amount >= 0", name="ck_order_snapshots_amount_non_negative"
        ),
    )


class OrderEvent(Base):
    """Append-only audit record for every order lifecycle and operational event."""

    __tablename__ = "order_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_ref: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(40), nullable=True)

    actor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(24), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    customer_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    customer_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )

    order: Mapped["Order"] = relationship("Order", back_populates="events")

    __table_args__ = (Index("ix_order_events_order_created", "order_id", "created_at"),)


class WorkflowTask(Base):
    """Operational tailoring task within a production or verification stage."""

    __tablename__ = "workflow_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_ref: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    stage: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    task_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=TaskStatus.PENDING.value, index=True
    )

    # Staff assignment is intentionally optional — never auto-invented
    assigned_staff_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_rework: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    checklist_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    material_ready: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    missing_material_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspection_result: Mapped[str | None] = mapped_column(String(48), nullable=True)
    approved_corrections: Mapped[str | None] = mapped_column(Text, nullable=True)
    rework_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    order: Mapped["Order"] = relationship("Order", back_populates="workflow_tasks")

    __table_args__ = (
        Index("ix_workflow_tasks_order_stage", "order_id", "stage"),
    )


class OrderNote(Base):
    """Order notes strictly segregated into INTERNAL vs CUSTOMER_VISIBLE."""

    __tablename__ = "order_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(24), nullable=False, default=NoteVisibility.INTERNAL.value, index=True
    )
    author_id: Mapped[str] = mapped_column(String(64), nullable=False)
    author_role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    order: Mapped["Order"] = relationship("Order", back_populates="notes")

    __table_args__ = (
        Index("ix_order_notes_order_visibility", "order_id", "visibility"),
    )


class CapacitySetting(Base):
    """Configurable workshop resource & workload warning settings (never hardcoded guarantees)."""

    __tablename__ = "capacity_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    config_key: Mapped[str] = mapped_column(
        String(32), nullable=False, unique=True, default="default"
    )
    sewing_machines_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    available_sewing_machines: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    overlock_machines_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    available_overlock_machines: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    irons_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    available_irons: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cutting_tables_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )
    available_cutting_tables: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    # Reported contextual reference (~2 shirt-and-pant sets/day); NEVER treated as guaranteed throughput
    reference_sets_per_day: Mapped[Decimal | None] = mapped_column(
        Numeric(8, 2), nullable=True
    )
    is_guaranteed_capacity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    max_active_production_orders_warning: Mapped[int] = mapped_column(
        Integer, nullable=False, default=6
    )
    max_stage_orders_warning: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3
    )
    max_urgent_orders_warning: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2
    )
    operating_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str] = mapped_column(
        String(64), nullable=False, default="SYSTEM"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    __table_args__ = (
        CheckConstraint(
            "sewing_machines_count >= 0 AND available_sewing_machines >= 0 "
            "AND available_sewing_machines <= sewing_machines_count",
            name="ck_capacity_sewing_machines",
        ),
        CheckConstraint(
            "overlock_machines_count >= 0 AND available_overlock_machines >= 0 "
            "AND available_overlock_machines <= overlock_machines_count",
            name="ck_capacity_overlock_machines",
        ),
        CheckConstraint(
            "irons_count >= 0 AND available_irons >= 0 AND available_irons <= irons_count",
            name="ck_capacity_irons",
        ),
        CheckConstraint(
            "cutting_tables_count >= 0 AND available_cutting_tables >= 0 "
            "AND available_cutting_tables <= cutting_tables_count",
            name="ck_capacity_cutting_tables",
        ),
        CheckConstraint(
            "max_active_production_orders_warning >= 1 AND max_stage_orders_warning >= 1",
            name="ck_capacity_thresholds_positive",
        ),
    )


class NotificationEvent(Base):
    """Persisted notification event outbox decoupled from external message providers."""

    __tablename__ = "notification_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    notification_ref: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    order_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="IN_APP")
    recipient_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    delivery_status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=NotificationDeliveryStatus.PENDING.value,
        index=True,
    )
    provider_name: Mapped[str] = mapped_column(
        String(32), nullable=False, default="mock"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    order: Mapped["Order"] = relationship("Order", back_populates="notifications")


# Enforce strict ORM-level immutability on OrderSnapshot and OrderEvent
@event.listens_for(OrderSnapshot, "before_update")
def _forbid_snapshot_update(_mapper: Any, _connection: Any, _target: Any) -> None:
    raise ImmutableRecordError(
        "Confirmed order snapshots are immutable and cannot be modified."
    )


@event.listens_for(OrderSnapshot, "before_delete")
def _forbid_snapshot_delete(_mapper: Any, _connection: Any, _target: Any) -> None:
    raise ImmutableRecordError(
        "Confirmed order snapshots are immutable and cannot be deleted."
    )


@event.listens_for(OrderEvent, "before_update")
def _forbid_event_update(_mapper: Any, _connection: Any, _target: Any) -> None:
    raise ImmutableRecordError("Order audit events are append-only and immutable.")


@event.listens_for(OrderEvent, "before_delete")
def _forbid_event_delete(_mapper: Any, _connection: Any, _target: Any) -> None:
    raise ImmutableRecordError("Order audit events cannot be deleted.")
