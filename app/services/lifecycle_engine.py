"""Centralized Order Lifecycle & Status Transition Engine (Phases 04 & 06).

All status transitions MUST pass through `LifecycleEngine.transition(...)`.
Scattered status mutations across endpoints are strictly prohibited.
"""

from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.core.enums import (
    ActorRole,
    InspectionResult,
    NotificationEventType,
    OrderStatus,
    SnapshotType,
    TaskStatus,
    WorkflowStage,
)
from app.core.exceptions import (
    ConcurrencyConflictError,
    ForbiddenError,
    ValidationError,
)
from app.core.security import Principal
from app.models.entities import Order, OrderEvent, WorkflowTask, utc_now
from app.services.identifiers import generate_public_ref
from app.services.notification_service import NotificationService
from app.services.snapshot_service import SnapshotService

STAFF_ROLES = {ActorRole.TAILOR, ActorRole.ADMIN, ActorRole.OWNER}
ADMIN_ROLES = {ActorRole.ADMIN, ActorRole.OWNER}

# Controlled standard forward transitions and allowed actor roles
STANDARD_TRANSITION_PERMISSIONS: dict[tuple[OrderStatus, OrderStatus], set[ActorRole]] = {
    (OrderStatus.DRAFT, OrderStatus.SUBMITTED): {
        ActorRole.CUSTOMER,
        ActorRole.ADMIN,
        ActorRole.OWNER,
        ActorRole.SYSTEM,
    },
    (OrderStatus.SUBMITTED, OrderStatus.UNDER_REVIEW): STAFF_ROLES,
    (OrderStatus.UNDER_REVIEW, OrderStatus.QUOTE_PENDING): STAFF_ROLES,
    (OrderStatus.UNDER_REVIEW, OrderStatus.AWAITING_CUSTOMER_CONFIRMATION): STAFF_ROLES,
    (OrderStatus.QUOTE_PENDING, OrderStatus.AWAITING_CUSTOMER_CONFIRMATION): STAFF_ROLES,
    # Re-quotation loops when quotation expires or scope changes before production starts
    (OrderStatus.AWAITING_CUSTOMER_CONFIRMATION, OrderStatus.QUOTE_PENDING): STAFF_ROLES,
    (OrderStatus.CONFIRMED, OrderStatus.AWAITING_CUSTOMER_CONFIRMATION): ADMIN_ROLES,
    # Customer confirmation into production queue
    (OrderStatus.AWAITING_CUSTOMER_CONFIRMATION, OrderStatus.CONFIRMED): {
        ActorRole.CUSTOMER,
        ActorRole.ADMIN,
        ActorRole.OWNER,
    },
    # Workshop production workflow
    (OrderStatus.CONFIRMED, OrderStatus.MATERIAL_PREPARATION): STAFF_ROLES,
    (OrderStatus.MATERIAL_PREPARATION, OrderStatus.CUTTING): STAFF_ROLES,
    (OrderStatus.CUTTING, OrderStatus.STITCHING): STAFF_ROLES,
    (OrderStatus.STITCHING, OrderStatus.FINISHING): STAFF_ROLES,
    (OrderStatus.FINISHING, OrderStatus.QUALITY_CHECK): STAFF_ROLES,
    (OrderStatus.QUALITY_CHECK, OrderStatus.READY): STAFF_ROLES,
    (OrderStatus.READY, OrderStatus.DELIVERED): STAFF_ROLES,
    (OrderStatus.DELIVERED, OrderStatus.COMPLETED): ADMIN_ROLES,
}

# Controlled rework transitions out of QUALITY_CHECK when inspection fails
REWORK_TARGETS: set[OrderStatus] = {
    OrderStatus.CUTTING,
    OrderStatus.STITCHING,
    OrderStatus.FINISHING,
}

# Controlled single-step administrative corrections (ADMIN/OWNER only, requires reason)
ADMIN_CORRECTION_TRANSITIONS: set[tuple[OrderStatus, OrderStatus]] = {
    (OrderStatus.MATERIAL_PREPARATION, OrderStatus.CONFIRMED),
    (OrderStatus.CUTTING, OrderStatus.MATERIAL_PREPARATION),
    (OrderStatus.STITCHING, OrderStatus.CUTTING),
    (OrderStatus.FINISHING, OrderStatus.STITCHING),
    (OrderStatus.READY, OrderStatus.QUALITY_CHECK),
    (OrderStatus.DELIVERED, OrderStatus.READY),
}

PRE_CONFIRMATION_CANCELLABLE_STATES: set[OrderStatus] = {
    OrderStatus.DRAFT,
    OrderStatus.SUBMITTED,
    OrderStatus.UNDER_REVIEW,
    OrderStatus.QUOTE_PENDING,
    OrderStatus.AWAITING_CUSTOMER_CONFIRMATION,
}

ADMIN_CANCELLABLE_ACTIVE_STATES: set[OrderStatus] = {
    OrderStatus.CONFIRMED,
    OrderStatus.MATERIAL_PREPARATION,
    OrderStatus.CUTTING,
    OrderStatus.STITCHING,
    OrderStatus.FINISHING,
    OrderStatus.QUALITY_CHECK,
    OrderStatus.READY,
    OrderStatus.ON_HOLD,
}

HOLDABLE_STATES: set[OrderStatus] = {
    OrderStatus.SUBMITTED,
    OrderStatus.UNDER_REVIEW,
    OrderStatus.QUOTE_PENDING,
    OrderStatus.AWAITING_CUSTOMER_CONFIRMATION,
    OrderStatus.CONFIRMED,
    OrderStatus.MATERIAL_PREPARATION,
    OrderStatus.CUTTING,
    OrderStatus.STITCHING,
    OrderStatus.FINISHING,
    OrderStatus.QUALITY_CHECK,
    OrderStatus.READY,
}

CUSTOMER_VISIBLE_STATUS_LABELS: dict[OrderStatus, str] = {
    OrderStatus.DRAFT: "Draft (Not Yet Submitted)",
    OrderStatus.SUBMITTED: "Order Submitted",
    OrderStatus.UNDER_REVIEW: "Under Tailoring Review",
    OrderStatus.QUOTE_PENDING: "Preparing Price Quotation",
    OrderStatus.AWAITING_CUSTOMER_CONFIRMATION: "Awaiting Your Price Confirmation",
    OrderStatus.CONFIRMED: "Order Confirmed for Tailoring",
    OrderStatus.MATERIAL_PREPARATION: "Preparing Fabric & Materials",
    OrderStatus.CUTTING: "Fabric Cutting in Progress",
    OrderStatus.STITCHING: "Stitching in Progress",
    OrderStatus.FINISHING: "Finishing & Pressing",
    OrderStatus.QUALITY_CHECK: "Quality Inspection",
    OrderStatus.READY: "Ready for Collection / Delivery",
    OrderStatus.DELIVERED: "Delivered / Collected",
    OrderStatus.COMPLETED: "Order Completed",
    OrderStatus.CANCELLED: "Order Cancelled",
    OrderStatus.ON_HOLD: "Order Temporarily on Hold",
}

STATUS_NOTIFICATION_MAP: dict[OrderStatus, NotificationEventType] = {
    OrderStatus.SUBMITTED: NotificationEventType.ORDER_SUBMITTED,
    OrderStatus.UNDER_REVIEW: NotificationEventType.ORDER_REVIEWED,
    OrderStatus.QUOTE_PENDING: NotificationEventType.QUOTATION_REQUESTED,
    OrderStatus.AWAITING_CUSTOMER_CONFIRMATION: NotificationEventType.PRICE_CONFIRMATION_REQUIRED,
    OrderStatus.CONFIRMED: NotificationEventType.ORDER_CONFIRMED,
    OrderStatus.CUTTING: NotificationEventType.CUTTING_STARTED,
    OrderStatus.STITCHING: NotificationEventType.STITCHING_STARTED,
    OrderStatus.READY: NotificationEventType.ORDER_READY,
    OrderStatus.DELIVERED: NotificationEventType.ORDER_DELIVERED,
    OrderStatus.COMPLETED: NotificationEventType.ORDER_COMPLETED,
    OrderStatus.CANCELLED: NotificationEventType.ORDER_CANCELLED,
    OrderStatus.ON_HOLD: NotificationEventType.ORDER_ON_HOLD,
}


class LifecycleEngine:
    """Centralized transactional state machine enforcing permissions, preconditions, and audit logs."""

    def __init__(
        self,
        *,
        snapshot_service: SnapshotService,
        notification_service: NotificationService,
    ) -> None:
        self._snapshot_service = snapshot_service
        self._notification_service = notification_service

    def transition(
        self,
        session: Session,
        *,
        order: Order,
        target_status: OrderStatus,
        principal: Principal,
        reason: str | None = None,
        expected_version: int | None = None,
        is_admin_correction: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> Order:
        if expected_version is not None and order.version != expected_version:
            raise ConcurrencyConflictError(
                f"Order version conflict: expected version {expected_version}, "
                f"but current version is {order.version}.",
                details={
                    "expected_version": expected_version,
                    "actual_version": order.version,
                },
            )

        current_status = OrderStatus(order.current_status)
        if current_status == target_status:
            raise ValidationError(
                f"Order is already in status '{current_status.value}'.",
                error_code="NO_OP_TRANSITION",
            )

        if current_status in {OrderStatus.COMPLETED, OrderStatus.CANCELLED}:
            raise ValidationError(
                f"Order in terminal status '{current_status.value}' cannot transition to '{target_status.value}'.",
                error_code="TERMINAL_STATE_IMMUTABLE",
            )

        # Enforce customer ownership whenever caller is a CUSTOMER
        if principal.role == ActorRole.CUSTOMER and order.customer_ref != principal.actor_id:
            raise ForbiddenError("Customers can only act on their own orders.")

        cleaned_reason = (reason or "").strip() or None
        extra_meta = dict(metadata or {})
        event_type = "STATUS_TRANSITION"
        customer_message: str | None = None

        # 1. Handle Cancellation
        if target_status == OrderStatus.CANCELLED:
            self._validate_cancellation(
                order=order,
                current_status=current_status,
                principal=principal,
                reason=cleaned_reason,
            )
            order.cancellation_reason = cleaned_reason
            order.cancelled_by = principal.actor_id
            order.cancelled_at = utc_now()
            event_type = "ORDER_CANCELLED"
            customer_message = f"Order was cancelled: {cleaned_reason}"

        # 2. Handle Placing on Hold
        elif target_status == OrderStatus.ON_HOLD:
            if principal.role not in STAFF_ROLES:
                raise ForbiddenError("Only authorized workshop/admin staff may place an order on hold.")
            if current_status not in HOLDABLE_STATES:
                raise ValidationError(
                    f"Order in status '{current_status.value}' cannot be placed ON_HOLD.",
                    error_code="INVALID_HOLD_STATE",
                )
            if not cleaned_reason:
                raise ValidationError(
                    "A reason is required when placing an order ON_HOLD.",
                    error_code="HOLD_REASON_REQUIRED",
                )
            order.previous_hold_status = current_status.value
            order.hold_reason = cleaned_reason
            event_type = "ORDER_PLACED_ON_HOLD"
            customer_message = f"Order placed temporarily on hold: {cleaned_reason}"

        # 3. Handle Resuming from Hold
        elif current_status == OrderStatus.ON_HOLD:
            if principal.role not in STAFF_ROLES:
                raise ForbiddenError("Only authorized workshop/admin staff may resume a held order.")
            prior = (
                OrderStatus(order.previous_hold_status)
                if order.previous_hold_status
                else OrderStatus.UNDER_REVIEW
            )
            allowed_resume_targets = {prior}
            if principal.role in ADMIN_ROLES:
                allowed_resume_targets.add(OrderStatus.UNDER_REVIEW)
            if target_status not in allowed_resume_targets:
                raise ValidationError(
                    f"Held order must resume to '{prior.value}' (requested '{target_status.value}').",
                    error_code="INVALID_RESUME_TARGET",
                    details={"expected_resume_status": prior.value},
                )
            extra_meta["resumed_from_prior_status"] = prior.value
            order.previous_hold_status = None
            order.hold_reason = None
            event_type = "ORDER_RESUMED_FROM_HOLD"
            customer_message = f"Order resumed into '{CUSTOMER_VISIBLE_STATUS_LABELS[target_status]}'."

        # 4. Handle Quality Check Rework transitions
        elif (
            current_status == OrderStatus.QUALITY_CHECK
            and target_status in REWORK_TARGETS
        ):
            if principal.role not in STAFF_ROLES:
                raise ForbiddenError("Only workshop/admin staff can trigger quality rework.")
            if not cleaned_reason:
                raise ValidationError(
                    "Rework instructions/reason are required when returning an order from QUALITY_CHECK.",
                    error_code="REWORK_REASON_REQUIRED",
                )
            order.latest_inspection_result = InspectionResult.FAILED_REWORK_REQUIRED.value
            order.rework_count += 1
            rework_stage_map = {
                OrderStatus.CUTTING: WorkflowStage.CUTTING.value,
                OrderStatus.STITCHING: WorkflowStage.STITCHING.value,
                OrderStatus.FINISHING: WorkflowStage.FINISHING.value,
            }
            rework_task = WorkflowTask(
                task_ref=generate_public_ref("TSK"),
                order_id=order.id,
                stage=rework_stage_map[target_status],
                task_name=f"Approved Rework ({target_status.value.title()}) #{order.rework_count}",
                task_status=TaskStatus.PENDING.value,
                is_rework=True,
                rework_requirements=cleaned_reason,
                notes=cleaned_reason,
                created_by=principal.actor_id,
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            session.add(rework_task)
            event_type = "QUALITY_REWORK_TRIGGERED"
            extra_meta["rework_count"] = order.rework_count
            customer_message = "Additional tailoring refinement in progress following quality inspection."

        # 5. Handle Exceptional Single-Step Administrative Correction
        elif is_admin_correction:
            if principal.role not in ADMIN_ROLES:
                raise ForbiddenError(
                    "Only ADMIN or OWNER may perform an administrative stage correction."
                )
            if (current_status, target_status) not in ADMIN_CORRECTION_TRANSITIONS:
                raise ValidationError(
                    f"Administrative correction from '{current_status.value}' to "
                    f"'{target_status.value}' is not permitted.",
                    error_code="INVALID_ADMIN_CORRECTION",
                )
            if not cleaned_reason or len(cleaned_reason) < 8:
                raise ValidationError(
                    "Administrative stage corrections require an explicit audit reason (>=8 chars).",
                    error_code="ADMIN_CORRECTION_REASON_REQUIRED",
                )
            event_type = "ADMIN_STAGE_CORRECTION"
            customer_message = f"Order stage updated to '{CUSTOMER_VISIBLE_STATUS_LABELS[target_status]}'."

        # 6. Standard Forward Workflow Transitions
        else:
            allowed_roles = STANDARD_TRANSITION_PERMISSIONS.get(
                (current_status, target_status)
            )
            if allowed_roles is None:
                raise ValidationError(
                    f"Invalid status transition from '{current_status.value}' to '{target_status.value}'.",
                    error_code="INVALID_STATUS_TRANSITION",
                    details={
                        "current_status": current_status.value,
                        "requested_status": target_status.value,
                    },
                )
            if principal.role not in allowed_roles:
                raise ForbiddenError(
                    f"Role '{principal.role.value}' cannot transition order from "
                    f"'{current_status.value}' to '{target_status.value}'."
                )

            customer_message = self._enforce_forward_business_conditions(
                session=session,
                order=order,
                current_status=current_status,
                target_status=target_status,
                principal=principal,
                reason=cleaned_reason,
                metadata=extra_meta,
            )

        # Apply status update, audit event, and notification atomically
        order.current_status = target_status.value
        order.updated_at = utc_now()

        audit_event = OrderEvent(
            event_ref=generate_public_ref("EVT"),
            order_id=order.id,
            event_type=event_type,
            previous_status=current_status.value,
            new_status=target_status.value,
            actor_id=principal.actor_id,
            actor_role=principal.role.value,
            reason=cleaned_reason,
            customer_visible=not is_admin_correction or True,
            customer_message=customer_message
            or CUSTOMER_VISIBLE_STATUS_LABELS[target_status],
            metadata_json=extra_meta,
            created_at=utc_now(),
        )
        session.add(audit_event)

        try:
            session.flush()
        except StaleDataError as exc:
            session.rollback()
            raise ConcurrencyConflictError(
                "Concurrent modification detected; the order was updated by another transaction."
            ) from exc

        # Emit domain notification event where mapped
        if current_status == OrderStatus.ON_HOLD and target_status != OrderStatus.CANCELLED:
            self._notification_service.emit(
                session,
                order=order,
                event_type=NotificationEventType.ORDER_RESUMED,
                payload={"status": target_status.value},
            )
        elif target_status in STATUS_NOTIFICATION_MAP:
            self._notification_service.emit(
                session,
                order=order,
                event_type=STATUS_NOTIFICATION_MAP[target_status],
                payload={"status": target_status.value},
            )

        return order

    def _validate_cancellation(
        self,
        *,
        order: Order,
        current_status: OrderStatus,
        principal: Principal,
        reason: str | None,
    ) -> None:
        if not reason:
            raise ValidationError(
                "A cancellation reason is required.",
                error_code="CANCELLATION_REASON_REQUIRED",
            )
        if current_status in {OrderStatus.DELIVERED, OrderStatus.COMPLETED}:
            raise ValidationError(
                f"Order in status '{current_status.value}' cannot be cancelled.",
                error_code="INVALID_CANCELLATION_STATE",
            )
        if current_status in PRE_CONFIRMATION_CANCELLABLE_STATES:
            if principal.role not in {
                ActorRole.CUSTOMER,
                ActorRole.ADMIN,
                ActorRole.OWNER,
            }:
                raise ForbiddenError(
                    "Only the owning customer or an administrator may cancel an unconfirmed order."
                )
            return

        if current_status in ADMIN_CANCELLABLE_ACTIVE_STATES:
            if principal.role not in ADMIN_ROLES:
                raise ForbiddenError(
                    "Orders that are already confirmed or in production can only be cancelled by ADMIN or OWNER."
                )
            return

        raise ValidationError(
            f"Cancellation from status '{current_status.value}' is not allowed.",
            error_code="INVALID_CANCELLATION_STATE",
        )

    def _enforce_forward_business_conditions(
        self,
        *,
        session: Session,
        order: Order,
        current_status: OrderStatus,
        target_status: OrderStatus,
        principal: Principal,
        reason: str | None,
        metadata: dict[str, Any],
    ) -> str:
        if target_status == OrderStatus.AWAITING_CUSTOMER_CONFIRMATION:
            quotation = self._snapshot_service.verify_quotation(order)
            order.quoted_amount = quotation.quoted_amount
            if current_status == OrderStatus.CONFIRMED:
                # Re-quotation invalidates prior confirmation flag until customer reconfirms
                if not reason:
                    raise ValidationError(
                        "Re-opening customer confirmation from CONFIRMED requires an explicit reason."
                    )
                order.customer_price_confirmed = False
                return "Updated quotation ready; awaiting customer price reconfirmation."
            return f"Quotation {quotation.quotation_id} ({quotation.currency} {quotation.quoted_amount}) ready for customer confirmation."

        if target_status == OrderStatus.CONFIRMED:
            # Must verify quotation, measurement, design, fabric, and create immutable snapshot!
            snap_type = (
                SnapshotType.REQUOTATION_RECONFIRMATION
                if len(order.snapshots) > 0
                else SnapshotType.ORDER_CONFIRMATION
            )
            if principal.role in ADMIN_ROLES and not order.customer_price_confirmed:
                # Admin can only confirm on customer's behalf if explicit customer_confirmation_ref is supplied
                if not metadata.get("customer_confirmation_evidence"):
                    raise ValidationError(
                        "Customer must confirm the quoted price before an order enters CONFIRMED "
                        "(or admin must record explicit customer_confirmation_evidence).",
                        error_code="CUSTOMER_PRICE_CONFIRMATION_REQUIRED",
                    )
            order.customer_price_confirmed = True
            order.customer_confirmed_at = utc_now()
            order.customer_confirmed_by = principal.actor_id
            snapshot = self._snapshot_service.create_confirmation_snapshot(
                session,
                order=order,
                principal=principal,
                snapshot_type=snap_type,
            )
            metadata["snapshot_version"] = snapshot.snapshot_version
            metadata["confirmed_amount"] = str(snapshot.confirmed_amount)
            return (
                f"Order confirmed with immutable snapshot v{snapshot.snapshot_version} "
                f"({snapshot.currency} {snapshot.confirmed_amount})."
            )

        if target_status == OrderStatus.CUTTING:
            # Ensure no unresolved material block tasks exist
            blocked_prep = [
                t
                for t in order.workflow_tasks
                if t.stage == WorkflowStage.MATERIAL_PREPARATION.value
                and (
                    t.task_status == TaskStatus.BLOCKED.value
                    or t.material_ready is False
                )
            ]
            if blocked_prep:
                raise ValidationError(
                    "Cannot advance to CUTTING while material preparation has missing or unready fabric.",
                    error_code="MATERIAL_NOT_READY",
                )

        if target_status == OrderStatus.READY:
            if order.latest_inspection_result not in {
                InspectionResult.PASSED.value,
                InspectionResult.PASSED_WITH_APPROVED_CORRECTION.value,
            }:
                raise ValidationError(
                    "Order cannot move to READY until QUALITY_CHECK records a PASSED or "
                    "PASSED_WITH_APPROVED_CORRECTION inspection result.",
                    error_code="QUALITY_CHECK_NOT_PASSED",
                )

        if target_status == OrderStatus.DELIVERED:
            delivery_method = str(
                metadata.get("delivery_method") or order.delivery_method or ""
            ).strip()
            delivery_ref = str(
                metadata.get("delivery_reference") or order.delivery_reference or ""
            ).strip()
            recipient_ack = str(
                metadata.get("delivery_recipient_ack")
                or order.delivery_recipient_ack
                or ""
            ).strip()
            if not delivery_method or not delivery_ref:
                raise ValidationError(
                    "Recording transition to DELIVERED requires delivery_method (e.g., COLLECTION or DELIVERY) "
                    "and delivery_reference.",
                    error_code="DELIVERY_EVIDENCE_REQUIRED",
                )
            order.delivery_method = delivery_method.upper()
            order.delivery_reference = delivery_ref
            if recipient_ack:
                order.delivery_recipient_ack = recipient_ack
            order.delivered_at = utc_now()
            return f"Order handed over via {order.delivery_method} (ref: {order.delivery_reference})."

        if target_status == OrderStatus.COMPLETED:
            # Section 6 & 14.G: An order must NOT be marked COMPLETED merely because production finished.
            if not order.delivered_at or not order.delivery_reference:
                raise ValidationError(
                    "Order cannot be marked COMPLETED without verified delivery/collection records.",
                    error_code="DELIVERY_NOT_VERIFIED",
                )
            if not order.customer_price_confirmed or len(order.snapshots) == 0:
                raise ValidationError(
                    "Order cannot be marked COMPLETED without a confirmed snapshot.",
                    error_code="SNAPSHOT_MISSING",
                )
            open_tasks = [
                t
                for t in order.workflow_tasks
                if t.task_status
                in {
                    TaskStatus.PENDING.value,
                    TaskStatus.IN_PROGRESS.value,
                    TaskStatus.BLOCKED.value,
                }
            ]
            if open_tasks:
                raise ValidationError(
                    "Order cannot be marked COMPLETED while workflow tasks remain unfinished.",
                    error_code="OPEN_WORKFLOW_TASKS",
                    details={"open_task_refs": [t.task_ref for t in open_tasks]},
                )
            evidence = str(
                metadata.get("completion_evidence")
                or order.completion_evidence
                or reason
                or ""
            ).strip()
            if not evidence:
                raise ValidationError(
                    "Marking an order COMPLETED requires explicit completion_evidence.",
                    error_code="COMPLETION_EVIDENCE_REQUIRED",
                )
            order.completion_evidence = evidence
            order.completed_by = principal.actor_id
            order.completed_at = utc_now()
            return "Order verified and formally closed as COMPLETED."

        return CUSTOMER_VISIBLE_STATUS_LABELS[target_status]
