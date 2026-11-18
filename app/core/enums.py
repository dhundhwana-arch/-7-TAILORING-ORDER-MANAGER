"""Domain enumerations for Module 07 (Tailoring Order Manager).

NOTE: Lifecycle statuses and actor roles are implemented as centralized,
configurable domain constants pending final sign-off across Modules 01 and 08.
"""

from enum import StrEnum


class OrderStatus(StrEnum):
    """Proposed controlled lifecycle statuses for tailoring orders."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    QUOTE_PENDING = "QUOTE_PENDING"
    AWAITING_CUSTOMER_CONFIRMATION = "AWAITING_CUSTOMER_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    MATERIAL_PREPARATION = "MATERIAL_PREPARATION"
    CUTTING = "CUTTING"
    STITCHING = "STITCHING"
    FINISHING = "FINISHING"
    QUALITY_CHECK = "QUALITY_CHECK"
    READY = "READY"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ON_HOLD = "ON_HOLD"


class ActorRole(StrEnum):
    """Proposed RBAC roles for authorization enforcement."""

    CUSTOMER = "CUSTOMER"
    TAILOR = "TAILOR"
    ADMIN = "ADMIN"
    OWNER = "OWNER"
    SYSTEM = "SYSTEM"


class FabricSource(StrEnum):
    """Distinguishes customer-supplied cloth from Module 02 catalogue inventory."""

    CUSTOMER_SUPPLIED = "CUSTOMER_SUPPLIED"
    BUSINESS_INVENTORY = "BUSINESS_INVENTORY"


class WorkflowStage(StrEnum):
    """Operational tailoring stages tracked via workflow tasks."""

    ORDER_REVIEW = "ORDER_REVIEW"
    MATERIAL_PREPARATION = "MATERIAL_PREPARATION"
    CUTTING = "CUTTING"
    STITCHING = "STITCHING"
    FINISHING = "FINISHING"
    QUALITY_CHECK = "QUALITY_CHECK"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERY_COMPLETION = "DELIVERY_COMPLETION"


class TaskStatus(StrEnum):
    """Execution states for individual workflow tasks."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class InspectionResult(StrEnum):
    """Outcomes recorded during the QUALITY_CHECK stage."""

    PASSED = "PASSED"
    PASSED_WITH_APPROVED_CORRECTION = "PASSED_WITH_APPROVED_CORRECTION"
    FAILED_REWORK_REQUIRED = "FAILED_REWORK_REQUIRED"


class NoteVisibility(StrEnum):
    """Strict separation between internal workshop notes and customer-visible updates."""

    INTERNAL = "INTERNAL"
    CUSTOMER_VISIBLE = "CUSTOMER_VISIBLE"


class SnapshotType(StrEnum):
    """Classification of immutable order snapshots."""

    ORDER_CONFIRMATION = "ORDER_CONFIRMATION"
    REQUOTATION_RECONFIRMATION = "REQUOTATION_RECONFIRMATION"
    ADMIN_CORRECTION = "ADMIN_CORRECTION"


class NotificationEventType(StrEnum):
    """Domain notification event types generated independently of external delivery."""

    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_REVIEWED = "ORDER_REVIEWED"
    QUOTATION_REQUESTED = "QUOTATION_REQUESTED"
    PRICE_CONFIRMATION_REQUIRED = "PRICE_CONFIRMATION_REQUIRED"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    MATERIAL_PENDING = "MATERIAL_PENDING"
    CUTTING_STARTED = "CUTTING_STARTED"
    STITCHING_STARTED = "STITCHING_STARTED"
    QUALITY_CHECK_COMPLETED = "QUALITY_CHECK_COMPLETED"
    ORDER_READY = "ORDER_READY"
    ORDER_DELIVERED = "ORDER_DELIVERED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_ON_HOLD = "ORDER_ON_HOLD"
    ORDER_RESUMED = "ORDER_RESUMED"
    ORDER_COMPLETED = "ORDER_COMPLETED"


class NotificationDeliveryStatus(StrEnum):
    """Delivery tracking states for notification outbox records."""

    PENDING = "PENDING"
    SENT_MOCK = "SENT_MOCK"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
