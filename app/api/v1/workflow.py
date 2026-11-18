"""Tailoring Workflow, Review, Delivery, and Completion endpoints."""

from typing import Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_principal,
    get_db,
    get_order_service,
    get_workflow_service,
)
from app.api.serializers import build_page, serialize_order, serialize_task
from app.core.exceptions import ForbiddenError
from app.core.security import Principal
from app.schemas.common import PaginatedResponse
from app.schemas.orders import OrderResponse
from app.schemas.workflow import (
    CompleteOrderRequest,
    RecordDeliveryRequest,
    WorkflowTaskCreateRequest,
    WorkflowTaskResponse,
    WorkflowTaskUpdateRequest,
)
from app.services.lifecycle_engine import STAFF_ROLES
from app.services.order_service import OrderService
from app.services.workflow_service import WorkflowService

router = APIRouter(tags=["Workflow"])


@router.get("/orders/{order_id}/workflow")
def get_order_workflow(
    order_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    order_service: OrderService = Depends(get_order_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    if principal.role not in STAFF_ROLES:
        raise ForbiddenError("Only workshop/admin staff may view internal workflow details.")
    order = order_service.get_order_by_identifier(db, order_id)
    readiness = workflow_service.review_order_readiness(
        db, order=order, principal=principal
    )
    return {
        "order_reference": order.public_order_ref,
        "current_status": order.current_status,
        "latest_inspection_result": order.latest_inspection_result,
        "rework_count": order.rework_count,
        "review_summary": readiness,
        "tasks": [serialize_task(t) for t in order.workflow_tasks],
    }


@router.post("/orders/{order_id}/review")
def review_order(
    order_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    order_service: OrderService = Depends(get_order_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> dict[str, Any]:
    order = order_service.get_order_by_identifier(db, order_id)
    return workflow_service.review_order_readiness(
        db, order=order, principal=principal
    )


@router.post("/orders/{order_id}/deliver", response_model=OrderResponse)
def record_order_delivery(
    order_id: str,
    payload: RecordDeliveryRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    order_service: OrderService = Depends(get_order_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> OrderResponse:
    order = order_service.get_order_by_identifier(db, order_id)
    updated = workflow_service.record_delivery(
        db,
        order=order,
        principal=principal,
        delivery_method=payload.delivery_method,
        delivery_reference=payload.delivery_reference,
        delivery_recipient_ack=payload.delivery_recipient_ack,
        expected_version=payload.expected_version,
    )
    return serialize_order(updated, principal=principal)


@router.post("/orders/{order_id}/complete", response_model=OrderResponse)
def complete_order(
    order_id: str,
    payload: CompleteOrderRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    order_service: OrderService = Depends(get_order_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> OrderResponse:
    order = order_service.get_order_by_identifier(db, order_id)
    updated = workflow_service.complete_order(
        db,
        order=order,
        principal=principal,
        completion_evidence=payload.completion_evidence,
        expected_version=payload.expected_version,
    )
    return serialize_order(updated, principal=principal)


@router.get("/workflow/tasks", response_model=PaginatedResponse[WorkflowTaskResponse])
def list_workflow_tasks(
    order_reference: str | None = Query(default=None),
    stage: str | None = Query(default=None),
    task_status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    order_service: OrderService = Depends(get_order_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> PaginatedResponse[WorkflowTaskResponse]:
    order_pk = None
    if order_reference:
        order_pk = order_service.get_order_by_identifier(db, order_reference).id
    tasks, total = workflow_service.list_tasks(
        db,
        principal=principal,
        order_id=order_pk,
        stage=stage,
        task_status=task_status,
        page=page,
        page_size=page_size,
    )
    return build_page(
        [serialize_task(t) for t in tasks],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post(
    "/workflow/tasks",
    response_model=WorkflowTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_task(
    payload: WorkflowTaskCreateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    order_service: OrderService = Depends(get_order_service),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowTaskResponse:
    order = order_service.get_order_by_identifier(db, payload.order_reference)
    task = workflow_service.create_task(
        db,
        order=order,
        principal=principal,
        stage=payload.stage,
        task_name=payload.task_name,
        assigned_staff_ref=payload.assigned_staff_ref,
        checklist=payload.checklist,
        material_ready=payload.material_ready,
        missing_material_info=payload.missing_material_info,
        notes=payload.notes,
    )
    return serialize_task(task)


@router.patch("/workflow/tasks/{task_id}", response_model=WorkflowTaskResponse)
def update_workflow_task(
    task_id: str,
    payload: WorkflowTaskUpdateRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_current_principal),
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowTaskResponse:
    task = workflow_service.update_task(
        db,
        task_identifier=task_id,
        principal=principal,
        task_status=payload.task_status,
        assigned_staff_ref=payload.assigned_staff_ref,
        checklist_updates=payload.checklist_updates,
        material_ready=payload.material_ready,
        missing_material_info=payload.missing_material_info,
        inspection_result=payload.inspection_result,
        approved_corrections=payload.approved_corrections,
        rework_requirements=payload.rework_requirements,
        notes=payload.notes,
    )
    return serialize_task(task)
