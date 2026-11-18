"""Workload & Capacity Awareness Service (Phase 07).

STRICT BUSINESS RULES (Sections 5 & 15):
1. Reported workshop resources (3 sewing machines, 1 overlock, 1 iron, 1 cutting table;
   ~2 shirt-and-pant sets/day) are contextual defaults ONLY — never hardcoded or
   treated as guaranteed throughput.
2. Never assumes simultaneous independent machine availability.
3. Never computes or promises automatic delivery dates.
4. Clearly separates estimated workload counts from verified resource availability,
   and surfaces warnings/conflicts for human administrator review when missing or exceeded.
"""

from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import OrderStatus
from app.core.exceptions import ForbiddenError, ValidationError
from app.core.security import Principal
from app.models.entities import CapacitySetting, Order, OrderItem, utc_now
from app.services.lifecycle_engine import ADMIN_ROLES, STAFF_ROLES

ACTIVE_PRODUCTION_STATUSES = {
    OrderStatus.CONFIRMED.value,
    OrderStatus.MATERIAL_PREPARATION.value,
    OrderStatus.CUTTING.value,
    OrderStatus.STITCHING.value,
    OrderStatus.FINISHING.value,
    OrderStatus.QUALITY_CHECK.value,
}

NON_TERMINAL_ACTIVE_STATUSES = {
    OrderStatus.SUBMITTED.value,
    OrderStatus.UNDER_REVIEW.value,
    OrderStatus.QUOTE_PENDING.value,
    OrderStatus.AWAITING_CUSTOMER_CONFIRMATION.value,
    *ACTIVE_PRODUCTION_STATUSES,
    OrderStatus.READY.value,
    OrderStatus.DELIVERED.value,
    OrderStatus.ON_HOLD.value,
}


class CapacityService:
    """Provides configurable workshop resource settings, workload counts, and non-binding warnings."""

    def get_settings_record(self, session: Session) -> CapacitySetting | None:
        return session.scalar(
            select(CapacitySetting).where(CapacitySetting.config_key == "default")
        )

    def get_capacity_overview(
        self, session: Session, *, principal: Principal
    ) -> dict[str, Any]:
        if principal.role not in STAFF_ROLES:
            raise ForbiddenError("Only workshop/admin staff may view capacity configuration.")

        setting = self.get_settings_record(session)
        if setting is None:
            return {
                "configured": False,
                "is_guaranteed_capacity": False,
                "delivery_date_policy": "NO_AUTOMATIC_DELIVERY_PROMISE",
                "warning": (
                    "Capacity settings have not been explicitly configured yet. "
                    "Administrator should configure verified workshop resources."
                ),
                "resources": None,
                "thresholds": None,
                "reference_sets_per_day": None,
                "operating_notes": None,
                "updated_by": None,
                "updated_at": None,
            }

        return self._serialize_setting(setting)

    def update_capacity_settings(
        self,
        session: Session,
        *,
        principal: Principal,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        if principal.role not in ADMIN_ROLES:
            raise ForbiddenError("Only ADMIN or OWNER may modify capacity settings.")

        setting = self.get_settings_record(session)
        if setting is None:
            setting = CapacitySetting(
                config_key="default",
                sewing_machines_count=3,
                available_sewing_machines=3,
                overlock_machines_count=1,
                available_overlock_machines=1,
                irons_count=1,
                available_irons=1,
                cutting_tables_count=1,
                available_cutting_tables=1,
                reference_sets_per_day=Decimal("2.00"),
                is_guaranteed_capacity=False,
                max_active_production_orders_warning=6,
                max_stage_orders_warning=3,
                max_urgent_orders_warning=2,
                operating_notes="Contextual baseline; not guaranteed daily throughput.",
                updated_by=principal.actor_id,
                updated_at=utc_now(),
            )
            session.add(setting)

        int_fields = (
            "sewing_machines_count",
            "available_sewing_machines",
            "overlock_machines_count",
            "available_overlock_machines",
            "irons_count",
            "available_irons",
            "cutting_tables_count",
            "available_cutting_tables",
            "max_active_production_orders_warning",
            "max_stage_orders_warning",
            "max_urgent_orders_warning",
        )
        for field_name in int_fields:
            if field_name in updates and updates[field_name] is not None:
                val = int(updates[field_name])
                if val < 0:
                    raise ValidationError(f"{field_name} cannot be negative.")
                setattr(setting, field_name, val)

        if (
            setting.max_active_production_orders_warning < 1
            or setting.max_stage_orders_warning < 1
        ):
            raise ValidationError("Warning thresholds must be >= 1.")

        pairs = [
            ("available_sewing_machines", "sewing_machines_count"),
            ("available_overlock_machines", "overlock_machines_count"),
            ("available_irons", "irons_count"),
            ("available_cutting_tables", "cutting_tables_count"),
        ]
        for avail_attr, total_attr in pairs:
            if getattr(setting, avail_attr) > getattr(setting, total_attr):
                raise ValidationError(
                    f"{avail_attr} ({getattr(setting, avail_attr)}) cannot exceed {total_attr} ({getattr(setting, total_attr)})."
                )

        if "reference_sets_per_day" in updates:
            raw_ref = updates["reference_sets_per_day"]
            if raw_ref is None:
                setting.reference_sets_per_day = None
            else:
                dec = Decimal(str(raw_ref))
                if dec <= Decimal("0"):
                    raise ValidationError("reference_sets_per_day must be positive when set.")
                setting.reference_sets_per_day = dec

        if "operating_notes" in updates:
            setting.operating_notes = (
                (updates["operating_notes"] or "").strip() or None
            )

        # Explicitly enforce non-guaranteed semantics per business rule 5.4
        setting.is_guaranteed_capacity = False
        setting.updated_by = principal.actor_id
        setting.updated_at = utc_now()

        session.commit()
        session.refresh(setting)
        return self._serialize_setting(setting)

    def get_workload_summary(
        self, session: Session, *, principal: Principal
    ) -> dict[str, Any]:
        if principal.role not in STAFF_ROLES:
            raise ForbiddenError("Only workshop/admin staff may view workload summaries.")

        rows = session.execute(
            select(Order.current_status, func.count(Order.id)).group_by(
                Order.current_status
            )
        ).all()
        counts_by_status: dict[str, int] = {
            status: int(cnt) for status, cnt in rows
        }

        urgent_active = int(
            session.scalar(
                select(func.count(Order.id)).where(
                    Order.is_urgent.is_(True),
                    Order.current_status.in_(NON_TERMINAL_ACTIVE_STATUSES),
                )
            )
            or 0
        )

        estimated_active_garment_units = int(
            session.scalar(
                select(func.coalesce(func.sum(OrderItem.quantity), 0))
                .join(Order, OrderItem.order_id == Order.id)
                .where(Order.current_status.in_(ACTIVE_PRODUCTION_STATUSES))
            )
            or 0
        )

        submitted_cnt = counts_by_status.get(OrderStatus.SUBMITTED.value, 0)
        under_review_cnt = counts_by_status.get(OrderStatus.UNDER_REVIEW.value, 0)
        quote_pending_cnt = counts_by_status.get(OrderStatus.QUOTE_PENDING.value, 0)
        awaiting_cust_cnt = counts_by_status.get(
            OrderStatus.AWAITING_CUSTOMER_CONFIRMATION.value, 0
        )
        confirmed_cnt = counts_by_status.get(OrderStatus.CONFIRMED.value, 0)
        mat_prep_cnt = counts_by_status.get(OrderStatus.MATERIAL_PREPARATION.value, 0)
        cutting_cnt = counts_by_status.get(OrderStatus.CUTTING.value, 0)
        stitching_cnt = counts_by_status.get(OrderStatus.STITCHING.value, 0)
        finishing_cnt = counts_by_status.get(OrderStatus.FINISHING.value, 0)
        qc_cnt = counts_by_status.get(OrderStatus.QUALITY_CHECK.value, 0)
        ready_cnt = counts_by_status.get(OrderStatus.READY.value, 0)
        delivered_cnt = counts_by_status.get(OrderStatus.DELIVERED.value, 0)
        on_hold_cnt = counts_by_status.get(OrderStatus.ON_HOLD.value, 0)
        completed_cnt = counts_by_status.get(OrderStatus.COMPLETED.value, 0)
        cancelled_cnt = counts_by_status.get(OrderStatus.CANCELLED.value, 0)

        active_orders_cnt = sum(
            counts_by_status.get(st, 0) for st in NON_TERMINAL_ACTIVE_STATUSES
        )
        active_production_cnt = sum(
            counts_by_status.get(st, 0) for st in ACTIVE_PRODUCTION_STATUSES
        )

        setting = self.get_settings_record(session)
        warnings: list[dict[str, Any]] = []
        conflicts: list[dict[str, Any]] = []

        if setting is None:
            warnings.append(
                {
                    "code": "MISSING_CAPACITY_CONFIGURATION",
                    "severity": "WARNING",
                    "message": (
                        "Workshop capacity configuration has not been initialized. "
                        "Configure verified equipment availability via PATCH /api/v1/capacity/settings."
                    ),
                }
            )
        else:
            if active_production_cnt > setting.max_active_production_orders_warning:
                warnings.append(
                    {
                        "code": "ACTIVE_PRODUCTION_THRESHOLD_EXCEEDED",
                        "severity": "HIGH",
                        "message": (
                            f"Active production orders ({active_production_cnt}) exceed configured "
                            f"review threshold ({setting.max_active_production_orders_warning})."
                        ),
                    }
                )
            if urgent_active > setting.max_urgent_orders_warning:
                warnings.append(
                    {
                        "code": "URGENT_WORKLOAD_HIGH",
                        "severity": "HIGH",
                        "message": (
                            f"Urgent active orders ({urgent_active}) exceed warning threshold "
                            f"({setting.max_urgent_orders_warning})."
                        ),
                    }
                )
            for stage_label, stage_cnt in (
                ("MATERIAL_PREPARATION", mat_prep_cnt),
                ("CUTTING", cutting_cnt),
                ("STITCHING", stitching_cnt),
                ("FINISHING", finishing_cnt),
                ("QUALITY_CHECK", qc_cnt),
            ):
                if stage_cnt > setting.max_stage_orders_warning:
                    warnings.append(
                        {
                            "code": f"{stage_label}_STAGE_BACKLOG",
                            "severity": "MEDIUM",
                            "message": (
                                f"Orders in {stage_label} ({stage_cnt}) exceed stage warning "
                                f"threshold ({setting.max_stage_orders_warning})."
                            ),
                        }
                    )

            # Resource bottleneck / conflict detection without assuming simultaneous staff operation
            if cutting_cnt > 0 and setting.available_cutting_tables == 0:
                conflicts.append(
                    {
                        "code": "CUTTING_TABLE_UNAVAILABLE",
                        "stage": "CUTTING",
                        "message": f"{cutting_cnt} order(s) in CUTTING while available_cutting_tables is 0.",
                    }
                )
            elif cutting_cnt > setting.available_cutting_tables:
                conflicts.append(
                    {
                        "code": "CUTTING_TABLE_CONTENTION",
                        "stage": "CUTTING",
                        "message": (
                            f"{cutting_cnt} orders queued in CUTTING across "
                            f"{setting.available_cutting_tables} available cutting table(s)."
                        ),
                    }
                )

            if stitching_cnt > 0 and setting.available_sewing_machines == 0:
                conflicts.append(
                    {
                        "code": "SEWING_MACHINES_UNAVAILABLE",
                        "stage": "STITCHING",
                        "message": f"{stitching_cnt} order(s) in STITCHING while available_sewing_machines is 0.",
                    }
                )
            elif stitching_cnt > setting.available_sewing_machines:
                conflicts.append(
                    {
                        "code": "SEWING_MACHINE_CONTENTION",
                        "stage": "STITCHING",
                        "message": (
                            f"{stitching_cnt} orders in STITCHING vs {setting.available_sewing_machines} "
                            "available sewing machine(s) (simultaneous operator availability not assumed)."
                        ),
                    }
                )

            if finishing_cnt > 0 and setting.available_irons == 0:
                conflicts.append(
                    {
                        "code": "IRON_UNAVAILABLE",
                        "stage": "FINISHING",
                        "message": f"{finishing_cnt} order(s) in FINISHING while available_irons is 0.",
                    }
                )

        return {
            "capacity_configured": setting is not None,
            "is_guaranteed_capacity": False,
            "delivery_date_policy": "NO_AUTOMATIC_DELIVERY_PROMISE",
            "estimated_workload": {
                "active_orders": active_orders_cnt,
                "active_production_orders": active_production_cnt,
                "estimated_active_garment_units": estimated_active_garment_units,
                "submitted_orders": submitted_cnt,
                "orders_awaiting_review": submitted_cnt + under_review_cnt + quote_pending_cnt,
                "under_review_orders": under_review_cnt,
                "quote_pending_orders": quote_pending_cnt,
                "awaiting_customer_confirmation_orders": awaiting_cust_cnt,
                "confirmed_orders": confirmed_cnt,
                "orders_in_material_preparation": mat_prep_cnt,
                "orders_in_cutting": cutting_cnt,
                "orders_in_stitching": stitching_cnt,
                "orders_in_finishing": finishing_cnt,
                "pending_quality_checks": qc_cnt,
                "ready_orders": ready_cnt,
                "delivered_pending_completion": delivered_cnt,
                "on_hold_orders": on_hold_cnt,
                "urgent_orders": urgent_active,
                "completed_orders": completed_cnt,
                "cancelled_orders": cancelled_cnt,
            },
            "verified_resource_availability": (
                self._serialize_setting(setting)["resources"]
                if setting is not None
                else None
            ),
            "capacity_exceeded": len(warnings) > 0 or len(conflicts) > 0,
            "capacity_warnings": warnings,
            "scheduling_conflicts": conflicts,
        }

    def _serialize_setting(self, setting: CapacitySetting) -> dict[str, Any]:
        return {
            "configured": True,
            "is_guaranteed_capacity": setting.is_guaranteed_capacity,
            "delivery_date_policy": "NO_AUTOMATIC_DELIVERY_PROMISE",
            "warning": None,
            "resources": {
                "sewing_machines": {
                    "total": setting.sewing_machines_count,
                    "available": setting.available_sewing_machines,
                },
                "overlock_machines": {
                    "total": setting.overlock_machines_count,
                    "available": setting.available_overlock_machines,
                },
                "irons": {
                    "total": setting.irons_count,
                    "available": setting.available_irons,
                },
                "cutting_tables": {
                    "total": setting.cutting_tables_count,
                    "available": setting.available_cutting_tables,
                },
            },
            "thresholds": {
                "max_active_production_orders_warning": setting.max_active_production_orders_warning,
                "max_stage_orders_warning": setting.max_stage_orders_warning,
                "max_urgent_orders_warning": setting.max_urgent_orders_warning,
            },
            "reference_sets_per_day": (
                str(setting.reference_sets_per_day)
                if setting.reference_sets_per_day is not None
                else None
            ),
            "operating_notes": setting.operating_notes,
            "updated_by": setting.updated_by,
            "updated_at": setting.updated_at,
        }
