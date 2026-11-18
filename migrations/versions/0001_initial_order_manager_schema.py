"""Initial Module 07 Tailoring Order Manager schema.

Revision ID: 0001_initial
Revises: None
Create Date: 2026-11-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("public_order_ref", sa.String(length=64), nullable=False),
        sa.Column("customer_ref", sa.String(length=64), nullable=False),
        sa.Column("current_status", sa.String(length=40), nullable=False),
        sa.Column("previous_hold_status", sa.String(length=40), nullable=True),
        sa.Column("hold_reason", sa.Text(), nullable=True),
        sa.Column("order_source", sa.String(length=64), nullable=False),
        sa.Column("submission_reference", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("measurement_ref", sa.String(length=64), nullable=False),
        sa.Column("quotation_ref", sa.String(length=64), nullable=True),
        sa.Column("quoted_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("customer_price_confirmed", sa.Boolean(), nullable=False),
        sa.Column("customer_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("customer_confirmed_by", sa.String(length=64), nullable=True),
        sa.Column("is_urgent", sa.Boolean(), nullable=False),
        sa.Column("urgent_authorized_by", sa.String(length=64), nullable=True),
        sa.Column("customer_instructions", sa.Text(), nullable=True),
        sa.Column("tracking_token_hash", sa.String(length=128), nullable=False),
        sa.Column("latest_inspection_result", sa.String(length=48), nullable=True),
        sa.Column("rework_count", sa.Integer(), nullable=False),
        sa.Column("delivery_method", sa.String(length=32), nullable=True),
        sa.Column("delivery_reference", sa.String(length=128), nullable=True),
        sa.Column("delivery_recipient_ack", sa.Text(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completion_evidence", sa.Text(), nullable=True),
        sa.Column("completed_by", sa.String(length=64), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancellation_reason", sa.Text(), nullable=True),
        sa.Column("cancelled_by", sa.String(length=64), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_orders_version_positive"),
        sa.CheckConstraint("rework_count >= 0", name="ck_orders_rework_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_order_ref"),
        sa.UniqueConstraint(
            "customer_ref", "idempotency_key", name="uq_orders_customer_idempotency"
        ),
        sa.UniqueConstraint(
            "order_source",
            "submission_reference",
            name="uq_orders_source_submission_ref",
        ),
    )
    op.create_index("ix_orders_public_order_ref", "orders", ["public_order_ref"], unique=True)
    op.create_index("ix_orders_customer_ref", "orders", ["customer_ref"])
    op.create_index("ix_orders_current_status", "orders", ["current_status"])
    op.create_index("ix_orders_submission_reference", "orders", ["submission_reference"])
    op.create_index("ix_orders_is_urgent", "orders", ["is_urgent"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])
    op.create_index("ix_orders_status_created", "orders", ["current_status", "created_at"])

    op.create_table(
        "capacity_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("config_key", sa.String(length=32), nullable=False),
        sa.Column("sewing_machines_count", sa.Integer(), nullable=False),
        sa.Column("available_sewing_machines", sa.Integer(), nullable=False),
        sa.Column("overlock_machines_count", sa.Integer(), nullable=False),
        sa.Column("available_overlock_machines", sa.Integer(), nullable=False),
        sa.Column("irons_count", sa.Integer(), nullable=False),
        sa.Column("available_irons", sa.Integer(), nullable=False),
        sa.Column("cutting_tables_count", sa.Integer(), nullable=False),
        sa.Column("available_cutting_tables", sa.Integer(), nullable=False),
        sa.Column("reference_sets_per_day", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("is_guaranteed_capacity", sa.Boolean(), nullable=False),
        sa.Column("max_active_production_orders_warning", sa.Integer(), nullable=False),
        sa.Column("max_stage_orders_warning", sa.Integer(), nullable=False),
        sa.Column("max_urgent_orders_warning", sa.Integer(), nullable=False),
        sa.Column("operating_notes", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "sewing_machines_count >= 0 AND available_sewing_machines >= 0 "
            "AND available_sewing_machines <= sewing_machines_count",
            name="ck_capacity_sewing_machines",
        ),
        sa.CheckConstraint(
            "overlock_machines_count >= 0 AND available_overlock_machines >= 0 "
            "AND available_overlock_machines <= overlock_machines_count",
            name="ck_capacity_overlock_machines",
        ),
        sa.CheckConstraint(
            "irons_count >= 0 AND available_irons >= 0 AND available_irons <= irons_count",
            name="ck_capacity_irons",
        ),
        sa.CheckConstraint(
            "cutting_tables_count >= 0 AND available_cutting_tables >= 0 "
            "AND available_cutting_tables <= cutting_tables_count",
            name="ck_capacity_cutting_tables",
        ),
        sa.CheckConstraint(
            "max_active_production_orders_warning >= 1 AND max_stage_orders_warning >= 1",
            name="ck_capacity_thresholds_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("config_key"),
    )

    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("garment_type", sa.String(length=48), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("design_ref", sa.String(length=64), nullable=False),
        sa.Column("design_version", sa.String(length=32), nullable=True),
        sa.Column("fabric_source", sa.String(length=32), nullable=False),
        sa.Column("fabric_ref", sa.String(length=64), nullable=False),
        sa.Column("fabric_variant_ref", sa.String(length=64), nullable=True),
        sa.Column("preview_3d_ref", sa.String(length=64), nullable=True),
        sa.Column("customization_data", sa.JSON(), nullable=False),
        sa.Column("item_notes", sa.Text(), nullable=True),
        sa.CheckConstraint("quantity >= 1", name="ck_order_items_quantity_positive"),
        sa.CheckConstraint("line_number >= 1", name="ck_order_items_line_positive"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", "line_number", name="uq_order_items_line"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])

    op.create_table(
        "order_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("snapshot_type", sa.String(length=40), nullable=False),
        sa.Column("design_snapshot", sa.JSON(), nullable=False),
        sa.Column("fabric_snapshot", sa.JSON(), nullable=False),
        sa.Column("measurement_snapshot", sa.JSON(), nullable=False),
        sa.Column("quotation_snapshot", sa.JSON(), nullable=False),
        sa.Column("confirmed_amount", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("confirmed_by", sa.String(length=64), nullable=False),
        sa.Column("confirmed_role", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "snapshot_version >= 1", name="ck_order_snapshots_version_positive"
        ),
        sa.CheckConstraint(
            "confirmed_amount >= 0", name="ck_order_snapshots_amount_non_negative"
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id", "snapshot_version", name="uq_order_snapshots_version"
        ),
    )
    op.create_index("ix_order_snapshots_order_id", "order_snapshots", ["order_id"])

    op.create_table(
        "order_events",
        sa.Column("event_ref", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("previous_status", sa.String(length=40), nullable=True),
        sa.Column("new_status", sa.String(length=40), nullable=True),
        sa.Column("actor_id", sa.String(length=64), nullable=False),
        sa.Column("actor_role", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("customer_visible", sa.Boolean(), nullable=False),
        sa.Column("customer_message", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_ref"),
    )
    op.create_index("ix_order_events_event_ref", "order_events", ["event_ref"], unique=True)
    op.create_index("ix_order_events_order_id", "order_events", ["order_id"])
    op.create_index("ix_order_events_event_type", "order_events", ["event_type"])
    op.create_index("ix_order_events_created_at", "order_events", ["created_at"])
    op.create_index(
        "ix_order_events_order_created", "order_events", ["order_id", "created_at"]
    )

    op.create_table(
        "workflow_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_ref", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("task_name", sa.String(length=120), nullable=False),
        sa.Column("task_status", sa.String(length=24), nullable=False),
        sa.Column("assigned_staff_ref", sa.String(length=64), nullable=True),
        sa.Column("is_rework", sa.Boolean(), nullable=False),
        sa.Column("checklist_json", sa.JSON(), nullable=False),
        sa.Column("material_ready", sa.Boolean(), nullable=True),
        sa.Column("missing_material_info", sa.Text(), nullable=True),
        sa.Column("inspection_result", sa.String(length=48), nullable=True),
        sa.Column("approved_corrections", sa.Text(), nullable=True),
        sa.Column("rework_requirements", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_ref"),
    )
    op.create_index("ix_workflow_tasks_task_ref", "workflow_tasks", ["task_ref"], unique=True)
    op.create_index("ix_workflow_tasks_order_id", "workflow_tasks", ["order_id"])
    op.create_index("ix_workflow_tasks_stage", "workflow_tasks", ["stage"])
    op.create_index("ix_workflow_tasks_task_status", "workflow_tasks", ["task_status"])
    op.create_index(
        "ix_workflow_tasks_order_stage", "workflow_tasks", ["order_id", "stage"]
    )

    op.create_table(
        "order_notes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("visibility", sa.String(length=24), nullable=False),
        sa.Column("author_id", sa.String(length=64), nullable=False),
        sa.Column("author_role", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_order_notes_order_id", "order_notes", ["order_id"])
    op.create_index("ix_order_notes_visibility", "order_notes", ["visibility"])
    op.create_index(
        "ix_order_notes_order_visibility", "order_notes", ["order_id", "visibility"]
    )

    op.create_table(
        "notification_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("notification_ref", sa.String(length=64), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=48), nullable=False),
        sa.Column("channel", sa.String(length=24), nullable=False),
        sa.Column("recipient_ref", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("delivery_status", sa.String(length=24), nullable=False),
        sa.Column("provider_name", sa.String(length=32), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notification_ref"),
    )
    op.create_index(
        "ix_notification_events_notification_ref",
        "notification_events",
        ["notification_ref"],
        unique=True,
    )
    op.create_index("ix_notification_events_order_id", "notification_events", ["order_id"])
    op.create_index(
        "ix_notification_events_event_type", "notification_events", ["event_type"]
    )
    op.create_index(
        "ix_notification_events_delivery_status",
        "notification_events",
        ["delivery_status"],
    )


def downgrade() -> None:
    op.drop_table("notification_events")
    op.drop_table("order_notes")
    op.drop_table("workflow_tasks")
    op.drop_table("order_events")
    op.drop_table("order_snapshots")
    op.drop_table("order_items")
    op.drop_table("capacity_settings")
    op.drop_table("orders")
