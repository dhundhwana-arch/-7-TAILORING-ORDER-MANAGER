"""Operational Tailoring Workflow Service (Phase 06).

Manages workshop tasks across Order Review, Material Preparation, Cutting,
Stitching, Finishing (configurable checklist: buttons, cuffs, thread checks,
ironing, etc.), Quality Check (comparison vs confirmed snapshot, pass/rework),
Delivery recording, and verified Completion.

STRICT RULE: Task staff assignment is always optional and never auto-invented.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.core.enums import (
    InspectionResult,
    NotificationEventType,
    OrderStatus,
    TaskStatus,
    WorkflowStage,
)
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.core.security import Principal
from app.models.entities import Order, OrderEvent, WorkflowTask, utc_now
from app.services.identifiers import generate_public_ref, validate_reference_id
from app.services.lifecycle_engine import ADMIN_ROLES, STAFF_ROLES, LifecycleEngine
from app.services.notification_service import NotificationService

DEFAULT_FINISHING_CHECKLIST: dict[str, bool] = {
    "buttons": False,
    "cuffs": False,
    "thread_checks": False,
    "ironing": False,
}


class WorkflowService:
    """Service coordinating workshop tailoring tasks, inspections, and completion."""

    def __init__(
        self,
        *,
        adapters: AdapterRegistry,
        lifecycle_engine: LifecycleEngine,
        notification_service: NotificationService,
    ) -> None:
        self._adapters = adapters
        self._lifecycle = lifecycle_engine
        self._notifications = notification_service

    def review_order_readiness(
        self, session: Session, *, order: Order, principal: Principal
    ) -> dict[str, Any]:
        """Inspect order references (design, fabric, measurement, quotation) during Order Review."""
        if principal.role not in STAFF_ROLES:
            raise ForbiddenError("Only workshop/admin staff may execute order review.")

        missing_or_issues: list[str] = []

        # Measurement check
        m_rec = self._adapters.measurement.get_measurement(order.measurement_ref)
        measurement_ok = bool(m_rec and m_rec.is_verified)
        if m_rec is None:
            missing_or_issues.append(
                f"Measurement '{order.measurement_ref}' missing in Module 06."
            )
        elif not m_rec.is_verified:
            missing_or_issues.append(
                f"Measurement '{order.measurement_ref}' is not yet validated ({m_rec.validation_status})."
            )

        # Quotation check
        quotation_ok = False
        if not order.quotation_ref:
            missing_or_issues.append("Official Module 05 quotation_ref not yet attached.")
        else:
            q_rec = self._adapters.pricing.get_quotation(order.quotation_ref)
            if q_rec is None or not q_rec.is_currently_valid():
                missing_or_issues.append(
                    f"Quotation '{order.quotation_ref}' is invalid or expired."
                )
            else:
                quotation_ok = True

        # Design & fabric checks per item
        design_ok = True
        fabric_ok = True
        for item in order.items:
            d_rec = self._adapters.design.get_design(item.design_ref)
            if d_rec is None or not d_rec.is_valid:
                design_ok = False
                missing_or_issues.append(
                    f"Line {item.line_number}: invalid design '{item.design_ref}'."
                )
            f_rec = self._adapters.fabric.get_fabric(
                item.fabric_ref,
                variant_id=item.fabric_variant_ref,
                fabric_source=item.fabric_source,
            )
            if f_rec is None or not f_rec.is_usable_for_order:
                fabric_ok = False
                missing_or_issues.append(
                    f"Line {item.line_number}: unavailable fabric '{item.fabric_ref}'."
                )

        return {
            "order_reference": order.public_order_ref,
            "current_status": order.current_status,
            "design_verified": design_ok,
            "fabric_verified": fabric_ok,
            "measurement_verified": measurement_ok,
            "quotation_verified": quotation_ok,
            "customer_price_confirmed": order.customer_price_confirmed,
            "ready_for_customer_confirmation": (
                design_ok and fabric_ok and measurement_ok and quotation_ok
            ),
            "missing_or_issues": missing_or_issues,
        }

    def create_task(
        self,
        session: Session,
        *,
        order: Order,
        principal: Principal,
        stage: WorkflowStage,
        task_name: str,
        assigned_staff_ref: str | None = None,
        checklist: dict[str, bool] | None = None,
        material_ready: bool | None = None,
        missing_material_info: str | None = None,
        notes: str | None = None,
    ) -> WorkflowTask:
        if principal.role not in STAFF_ROLES:
            raise ForbiddenError("Only authorized workshop/admin staff may create workflow tasks.")
        if order.current_status in {
            OrderStatus.CANCELLED.value,
            OrderStatus.COMPLETED.value,
        }:
            raise ValidationError("Cannot create workflow tasks on a closed order.")

        cleaned_name = task_name.strip()
        if not cleaned_name:
            raise ValidationError("task_name cannot be empty.")

        clean_staff = validate_reference_id(
            assigned_staff_ref, field_name="assigned_staff_ref", required=False
        )

        effective_checklist: dict[str, Any] = {}
        if stage == WorkflowStage.FINISHING:
            effective_checklist = dict(
                checklist if checklist is not None else DEFAULT_FINISHING_CHECKLIST
            )
        elif checklist is not None:
            effective_checklist = dict(checklist)

        initial_status = TaskStatus.PENDING
        if stage == WorkflowStage.MATERIAL_PREPARATION and material_ready is False:
            initial_status = TaskStatus.BLOCKED

        task = WorkflowTask(
            task_ref=generate_public_ref("TSK"),
            order_id=order.id,
            stage=stage.value,
            task_name=cleaned_name,
            task_status=initial_status.value,
            assigned_staff_ref=clean_staff,
            is_rework=False,
            checklist_json=effective_checklist,
            material_ready=material_ready,
            missing_material_info=(missing_material_info or "").strip() or None,
            notes=(notes or "").strip() or None,
            created_by=principal.actor_id,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(task)
        session.add(
            OrderEvent(
                event_ref=generate_public_ref("EVT"),
                order_id=order.id,
                event_type="WORKFLOW_TASK_CREATED",
                previous_status=order.current_status,
                new_status=order.current_status,
                actor_id=principal.actor_id,
                actor_role=principal.role.value,
                reason=f"Created {stage.value} task '{cleaned_name}'",
                customer_visible=False,
                metadata_json={"task_ref": task.task_ref, "stage": stage.value},
                created_at=utc_now(),
            )
        )

        if stage == WorkflowStage.MATERIAL_PREPARATION and material_ready is False:
            self._notifications.emit(
                session,
                order=order,
                event_type=NotificationEventType.MATERIAL_PENDING,
                payload={
                    "missing_material_info": task.missing_material_info
                    or "Fabric/material pending verification"
                },
            )

        session.commit()
        session.refresh(task)
        return task

    def update_task(
        self,
        session: Session,
        *,
        task_identifier: str,
        principal: Principal,
        task_status: TaskStatus | None = None,
        assigned_staff_ref: str | None = None,
        checklist_updates: dict[str, bool] | None = None,
        material_ready: bool | None = None,
        missing_material_info: str | None = None,
        inspection_result: InspectionResult | None = None,
        approved_corrections: str | None = None,
        rework_requirements: str | None = None,
        notes: str | None = None,
    ) -> WorkflowTask:
        if principal.role not in STAFF_ROLES:
            raise ForbiddenError("Only authorized workshop/admin staff may update workflow tasks.")

        cleaned = task_identifier.strip()
        stmt = select(WorkflowTask).where(WorkflowTask.task_ref == cleaned)
        if cleaned.isdigit():
            stmt = select(WorkflowTask).where(
                (WorkflowTask.id == int(cleaned))
                | (WorkflowTask.task_ref == cleaned)
            )
        task = session.scalar(stmt)
        if task is None:
            raise NotFoundError(f"Workflow task '{cleaned}' was not found.")

        order = task.order

        if assigned_staff_ref is not None:
            task.assigned_staff_ref = validate_reference_id(
                assigned_staff_ref, field_name="assigned_staff_ref", required=False
            )

        if checklist_updates:
            merged = dict(task.checklist_json or {})
            for k, v in checklist_updates.items():
                merged[str(k)] = bool(v)
            task.checklist_json = merged

        if material_ready is not None:
            task.material_ready = material_ready
            if material_ready is False and task_status is None:
                task.task_status = TaskStatus.BLOCKED.value
                self._notifications.emit(
                    session,
                    order=order,
                    event_type=NotificationEventType.MATERIAL_PENDING,
                    payload={
                        "missing_material_info": missing_material_info
                        or task.missing_material_info
                        or "Material pending"
                    },
                )

        if missing_material_info is not None:
            task.missing_material_info = missing_material_info.strip() or None

        if approved_corrections is not None:
            task.approved_corrections = approved_corrections.strip() or None

        if rework_requirements is not None:
            task.rework_requirements = rework_requirements.strip() or None

        if notes is not None:
            task.notes = notes.strip() or None

        if inspection_result is not None:
            if task.stage != WorkflowStage.QUALITY_CHECK.value:
                raise ValidationError(
                    "inspection_result can only be recorded on QUALITY_CHECK tasks."
                )
            if (
                inspection_result == InspectionResult.FAILED_REWORK_REQUIRED
                and not (task.rework_requirements or rework_requirements)
            ):
                raise ValidationError(
                    "rework_requirements must be recorded when inspection_result is FAILED_REWORK_REQUIRED."
                )
            task.inspection_result = inspection_result.value
            order.latest_inspection_result = inspection_result.value
            self._notifications.emit(
                session,
                order=order,
                event_type=NotificationEventType.QUALITY_CHECK_COMPLETED,
                payload={"inspection_result": inspection_result.value},
            )

        if task_status is not None:
            if task_status == TaskStatus.IN_PROGRESS and task.started_at is None:
                task.started_at = utc_now()
            if task_status == TaskStatus.COMPLETED:
                # Enforce finishing checklist completion before closing a FINISHING task
                if task.stage == WorkflowStage.FINISHING.value and task.checklist_json:
                    incomplete = [
                        item_key
                        for item_key, done in task.checklist_json.items()
                        if not done
                    ]
                    if incomplete:
                        raise ValidationError(
                            f"Cannot complete FINISHING task until all checklist items are verified: {incomplete}.",
                            error_code="FINISHING_CHECKLIST_INCOMPLETE",
                            details={"incomplete_items": incomplete},
                        )
                if (
                    task.stage == WorkflowStage.MATERIAL_PREPARATION.value
                    and task.material_ready is False
                ):
                    raise ValidationError(
                        "Cannot complete MATERIAL_PREPARATION task while material_ready is False.",
                        error_code="MATERIAL_NOT_READY",
                    )
                if (
                    task.stage == WorkflowStage.QUALITY_CHECK.value
                    and not task.inspection_result
                ):
                    raise ValidationError(
                        "Cannot complete QUALITY_CHECK task without recording an inspection_result.",
                        error_code="INSPECTION_RESULT_REQUIRED",
                    )
                if task.started_at is None:
                    task.started_at = utc_now()
                task.completed_at = utc_now()

            task.task_status = task_status.value

        task.updated_at = utc_now()
        order.updated_at = utc_now()

        session.add(
            OrderEvent(
                event_ref=generate_public_ref("EVT"),
                order_id=order.id,
                event_type="WORKFLOW_TASK_UPDATED",
                previous_status=order.current_status,
                new_status=order.current_status,
                actor_id=principal.actor_id,
                actor_role=principal.role.value,
                reason=f"Updated workflow task {task.task_ref}",
                customer_visible=False,
                metadata_json={
                    "task_ref": task.task_ref,
                    "stage": task.stage,
                    "task_status": task.task_status,
                    "inspection_result": task.inspection_result,
                },
                created_at=utc_now(),
            )
        )

        session.commit()
        session.refresh(task)
        return task

    def list_tasks(
        self,
        session: Session,
        *,
        principal: Principal,
        order_id: int | None = None,
        stage: str | None = None,
        task_status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[WorkflowTask], int]:
        if principal.role not in STAFF_ROLES:
            raise ForbiddenError("Only workshop/admin staff may list workflow tasks.")

        stmt = select(WorkflowTask)
        count_stmt = select(func.count(WorkflowTask.id))

        if order_id is not None:
            stmt = stmt.where(WorkflowTask.order_id == order_id)
            count_stmt = count_stmt.where(WorkflowTask.order_id == order_id)
        if stage:
            stmt = stmt.where(WorkflowTask.stage == stage.strip().upper())
            count_stmt = count_stmt.where(WorkflowTask.stage == stage.strip().upper())
        if task_status:
            stmt = stmt.where(WorkflowTask.task_status == task_status.strip().upper())
            count_stmt = count_stmt.where(
                WorkflowTask.task_status == task_status.strip().upper()
            )

        total = int(session.scalar(count_stmt) or 0)
        offset = (page - 1) * page_size
        tasks = list(
            session.scalars(
                stmt.order_by(WorkflowTask.id.desc()).offset(offset).limit(page_size)
            ).all()
        )
        return tasks, total

    def record_delivery(
        self,
        session: Session,
        *,
        order: Order,
        principal: Principal,
        delivery_method: str,
        delivery_reference: str,
        delivery_recipient_ack: str | None = None,
        expected_version: int | None = None,
    ) -> Order:
        if principal.role not in STAFF_ROLES:
            raise ForbiddenError("Only authorized staff/admin may record order delivery.")
        self._lifecycle.transition(
            session,
            order=order,
            target_status=OrderStatus.DELIVERED,
            principal=principal,
            reason=f"Delivered via {delivery_method} ({delivery_reference})",
            expected_version=expected_version,
            metadata={
                "delivery_method": delivery_method,
                "delivery_reference": delivery_reference,
                "delivery_recipient_ack": delivery_recipient_ack,
            },
        )
        session.commit()
        session.refresh(order)
        return order

    def complete_order(
        self,
        session: Session,
        *,
        order: Order,
        principal: Principal,
        completion_evidence: str,
        expected_version: int | None = None,
    ) -> Order:
        if principal.role not in ADMIN_ROLES:
            raise ForbiddenError("Only ADMIN or OWNER may formally close an order as COMPLETED.")
        self._lifecycle.transition(
            session,
            order=order,
            target_status=OrderStatus.COMPLETED,
            principal=principal,
            reason="Verified order completion",
            expected_version=expected_version,
            metadata={"completion_evidence": completion_evidence},
        )
        session.commit()
        session.refresh(order)
        return order
