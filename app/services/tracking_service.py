"""Customer Order Tracking & Sanitized Timeline Service (Phase 08).

STRICT PRIVACY & AUTHORIZATION RULES (Sections 12, 16, 19):
1. Order reference alone NEVER authorizes access.
2. Access requires EITHER:
   - An authenticated CUSTOMER whose `actor_id == order.customer_ref`
   - An authenticated workshop/admin staff member (`TAILOR`, `ADMIN`, `OWNER`)
   - A valid cryptographic `tracking_token` verified in constant time against `order.tracking_token_hash`
3. NEVER exposes internal staff notes (`NoteVisibility.INTERNAL`), staff IDs, or private
   customer body measurement values (`measurement_snapshot.measurements`).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import ActorRole, NoteVisibility, OrderStatus
from app.core.exceptions import (
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
)
from app.core.security import Principal, verify_tracking_token
from app.models.entities import Order
from app.services.lifecycle_engine import (
    CUSTOMER_VISIBLE_STATUS_LABELS,
    STAFF_ROLES,
)

ORDERED_LIFECYCLE_PROGRESSION: list[OrderStatus] = [
    OrderStatus.SUBMITTED,
    OrderStatus.UNDER_REVIEW,
    OrderStatus.AWAITING_CUSTOMER_CONFIRMATION,
    OrderStatus.CONFIRMED,
    OrderStatus.MATERIAL_PREPARATION,
    OrderStatus.CUTTING,
    OrderStatus.STITCHING,
    OrderStatus.FINISHING,
    OrderStatus.QUALITY_CHECK,
    OrderStatus.READY,
    OrderStatus.DELIVERED,
    OrderStatus.COMPLETED,
]


class TrackingService:
    """Provides privacy-safe customer order tracking and chronological timelines."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_tracking_view(
        self,
        session: Session,
        *,
        order_reference: str,
        principal: Principal | None,
        tracking_token: str | None,
    ) -> dict[str, Any]:
        cleaned_ref = order_reference.strip()
        order = session.scalar(
            select(Order).where(Order.public_order_ref == cleaned_ref)
        )
        if order is None:
            # Verify caller at least presented credentials/token before revealing existence
            if principal is None and not (tracking_token or "").strip():
                raise UnauthorizedError(
                    "Tracking access requires authentication or a valid tracking token."
                )
            raise NotFoundError(f"Order '{cleaned_ref}' was not found.")

        self._authorize_tracking_access(
            order=order, principal=principal, tracking_token=tracking_token
        )

        current_st = OrderStatus(order.current_status)
        completed_stages, pending_stages = self._compute_stage_lists(order, current_st)

        timeline: list[dict[str, Any]] = []
        for ev in order.events:
            if not ev.customer_visible:
                continue
            timeline.append(
                {
                    "event_type": ev.event_type,
                    "status": ev.new_status,
                    "status_label": (
                        CUSTOMER_VISIBLE_STATUS_LABELS.get(
                            OrderStatus(ev.new_status), ev.new_status
                        )
                        if ev.new_status
                        else None
                    ),
                    "message": ev.customer_message
                    or (
                        CUSTOMER_VISIBLE_STATUS_LABELS.get(
                            OrderStatus(ev.new_status), ev.event_type
                        )
                        if ev.new_status
                        else ev.event_type
                    ),
                    "timestamp": ev.created_at,
                }
            )

        customer_updates = [
            {
                "message": note.content,
                "timestamp": note.created_at,
            }
            for note in order.notes
            if note.visibility == NoteVisibility.CUSTOMER_VISIBLE.value
        ]

        latest_update = timeline[-1]["message"] if timeline else None
        if customer_updates and (
            not timeline or customer_updates[-1]["timestamp"] >= timeline[-1]["timestamp"]
        ):
            latest_update = customer_updates[-1]["message"]

        delivery_info = None
        if order.delivered_at and order.delivery_method and order.delivery_reference:
            delivery_info = {
                "delivery_method": order.delivery_method,
                "delivery_reference": order.delivery_reference,
                "delivered_at": order.delivered_at,
            }

        return {
            "order_reference": order.public_order_ref,
            "current_status": current_st.value,
            "customer_status_label": CUSTOMER_VISIBLE_STATUS_LABELS[current_st],
            "created_at": order.created_at,
            "updated_at": order.updated_at,
            "latest_update": latest_update,
            "completed_stages": completed_stages,
            "pending_stages": pending_stages,
            "delivery_info": delivery_info,
            "customer_instructions": order.customer_instructions,
            "customer_updates": customer_updates,
            "timeline": timeline,
        }

    def _authorize_tracking_access(
        self,
        *,
        order: Order,
        principal: Principal | None,
        tracking_token: str | None,
    ) -> None:
        if principal is not None:
            if principal.role in STAFF_ROLES:
                return
            if (
                principal.role == ActorRole.CUSTOMER
                and principal.actor_id == order.customer_ref
            ):
                return
            raise ForbiddenError(
                "Access denied: you are not authorized to track another customer's order."
            )

        cleaned_token = (tracking_token or "").strip()
        if not cleaned_token:
            raise UnauthorizedError(
                "Order reference alone does not grant tracking access. Provide an authenticated "
                "Bearer token or valid tracking token."
            )
        if not verify_tracking_token(
            cleaned_token,
            order_ref=order.public_order_ref,
            expected_hash=order.tracking_token_hash,
            secret_key=self._settings.TRACKING_TOKEN_SECRET,
        ):
            raise ForbiddenError("Invalid tracking token for this order.")

    def _compute_stage_lists(
        self, order: Order, current_status: OrderStatus
    ) -> tuple[list[str], list[str]]:
        if current_status == OrderStatus.DRAFT:
            return [], [st.value for st in ORDERED_LIFECYCLE_PROGRESSION]

        if current_status in {OrderStatus.CANCELLED, OrderStatus.ON_HOLD}:
            reached_statuses = {
                ev.new_status
                for ev in order.events
                if ev.customer_visible and ev.new_status
            }
            completed = [
                st.value
                for st in ORDERED_LIFECYCLE_PROGRESSION
                if st.value in reached_statuses
            ]
            if current_status == OrderStatus.CANCELLED:
                return completed, []
            pending = [
                st.value
                for st in ORDERED_LIFECYCLE_PROGRESSION
                if st.value not in reached_statuses
            ]
            return completed, pending

        if current_status in ORDERED_LIFECYCLE_PROGRESSION:
            idx = ORDERED_LIFECYCLE_PROGRESSION.index(current_status)
            if current_status == OrderStatus.COMPLETED:
                return [st.value for st in ORDERED_LIFECYCLE_PROGRESSION], []
            completed = [st.value for st in ORDERED_LIFECYCLE_PROGRESSION[:idx]]
            pending = [st.value for st in ORDERED_LIFECYCLE_PROGRESSION[idx:]]
            return completed, pending

        return [], [st.value for st in ORDERED_LIFECYCLE_PROGRESSION]
