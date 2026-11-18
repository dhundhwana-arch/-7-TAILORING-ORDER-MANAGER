"""FastAPI dependency injection helpers."""

from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.adapters.registry import AdapterRegistry
from app.core.config import Settings
from app.core.security import AuthAdapter, Principal
from app.services.capacity_service import CapacityService
from app.services.lifecycle_engine import LifecycleEngine
from app.services.notification_service import NotificationService
from app.services.order_service import OrderService
from app.services.snapshot_service import SnapshotService
from app.services.tracking_service import TrackingService
from app.services.workflow_service import WorkflowService


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Generator[Session, None, None]:
    session_factory = request.app.state.session_factory
    session: Session = session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_adapters(request: Request) -> AdapterRegistry:
    return request.app.state.adapters


def get_auth_adapter(request: Request) -> AuthAdapter:
    return request.app.state.auth_adapter


def get_current_principal(
    request: Request, auth: AuthAdapter = Depends(get_auth_adapter)
) -> Principal:
    return auth.authenticate_request(request)


def get_optional_principal(
    request: Request, auth: AuthAdapter = Depends(get_auth_adapter)
) -> Principal | None:
    return auth.authenticate_optional(request)


def get_notification_service(
    adapters: AdapterRegistry = Depends(get_adapters),
) -> NotificationService:
    return NotificationService(adapters.notification)


def get_snapshot_service(
    adapters: AdapterRegistry = Depends(get_adapters),
) -> SnapshotService:
    return SnapshotService(adapters)


def get_lifecycle_engine(
    snapshot_service: SnapshotService = Depends(get_snapshot_service),
    notification_service: NotificationService = Depends(get_notification_service),
) -> LifecycleEngine:
    return LifecycleEngine(
        snapshot_service=snapshot_service,
        notification_service=notification_service,
    )


def get_order_service(
    settings: Settings = Depends(get_app_settings),
    adapters: AdapterRegistry = Depends(get_adapters),
    lifecycle_engine: LifecycleEngine = Depends(get_lifecycle_engine),
    snapshot_service: SnapshotService = Depends(get_snapshot_service),
    notification_service: NotificationService = Depends(get_notification_service),
) -> OrderService:
    return OrderService(
        settings=settings,
        adapters=adapters,
        lifecycle_engine=lifecycle_engine,
        snapshot_service=snapshot_service,
        notification_service=notification_service,
    )


def get_workflow_service(
    adapters: AdapterRegistry = Depends(get_adapters),
    lifecycle_engine: LifecycleEngine = Depends(get_lifecycle_engine),
    notification_service: NotificationService = Depends(get_notification_service),
) -> WorkflowService:
    return WorkflowService(
        adapters=adapters,
        lifecycle_engine=lifecycle_engine,
        notification_service=notification_service,
    )


def get_capacity_service() -> CapacityService:
    return CapacityService()


def get_tracking_service(
    settings: Settings = Depends(get_app_settings),
) -> TrackingService:
    return TrackingService(settings)
