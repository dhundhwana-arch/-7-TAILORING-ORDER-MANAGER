"""Notification event outbox and mock provider dispatch service.

STRICT RULE (Section 18):
- Never sends real customer notifications during development.
- Separates notification event persistence (`notification_events` table) from
  external provider delivery (`NotificationProvider`).
"""

from typing import Any

from sqlalchemy.orm import Session

from app.adapters.contracts import NotificationProvider
from app.core.enums import NotificationDeliveryStatus, NotificationEventType
from app.core.logging import logger
from app.models.entities import NotificationEvent, Order, utc_now
from app.services.identifiers import generate_public_ref


class NotificationService:
    """Records domain notification events and dispatches via the configured provider."""

    def __init__(self, provider: NotificationProvider) -> None:
        self._provider = provider

    def emit(
        self,
        session: Session,
        *,
        order: Order,
        event_type: NotificationEventType,
        payload: dict[str, Any],
        channel: str = "IN_APP",
        recipient_ref: str | None = None,
    ) -> NotificationEvent:
        notif_ref = generate_public_ref("NTF")
        target_recipient = recipient_ref or order.customer_ref
        safe_payload = {
            "order_reference": order.public_order_ref,
            "event_type": event_type.value,
            **payload,
        }

        record = NotificationEvent(
            notification_ref=notif_ref,
            order_id=order.id,
            event_type=event_type.value,
            channel=channel,
            recipient_ref=target_recipient,
            payload_json=safe_payload,
            delivery_status=NotificationDeliveryStatus.PENDING.value,
            provider_name="mock",
            created_at=utc_now(),
        )
        session.add(record)
        session.flush()

        try:
            result = self._provider.dispatch(
                notification_ref=notif_ref,
                event_type=event_type.value,
                channel=channel,
                recipient_ref=target_recipient,
                payload=safe_payload,
            )
            record.provider_name = result.provider_name
            record.delivery_status = result.status_label
            record.error_message = result.error_message
            record.processed_at = utc_now()
        except Exception as exc:
            logger.warning(
                "Notification provider failed for %s (%s): %s",
                notif_ref,
                event_type.value,
                exc,
            )
            record.delivery_status = NotificationDeliveryStatus.FAILED.value
            record.error_message = str(exc)
            record.processed_at = utc_now()

        session.flush()
        return record
