"""Capacity & Workload awareness endpoints (`/api/v1/capacity`)."""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_capacity_service, get_current_principal, get_db
from app.core.security import Principal
from app.schemas.capacity import CapacitySettingsUpdateRequest
from app.services.capacity_service import CapacityService

router = APIRouter(prefix="/capacity", tags=["Capacity"])


@router.get("")
def get_capacity(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: CapacityService = Depends(get_capacity_service),
) -> dict[str, Any]:
    return service.get_capacity_overview(db, principal=principal)


@router.get("/workload")
def get_workload(
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: CapacityService = Depends(get_capacity_service),
) -> dict[str, Any]:
    return service.get_workload_summary(db, principal=principal)


@router.patch("/settings")
def update_capacity_settings(
    payload: CapacitySettingsUpdateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    service: CapacityService = Depends(get_capacity_service),
) -> dict[str, Any]:
    return service.update_capacity_settings(
        db,
        principal=principal,
        updates=payload.model_dump(exclude_unset=True),
    )
