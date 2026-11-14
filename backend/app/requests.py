import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints, field_serializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import administrator, branch_ids
from app.db import get_db
from app.models import (
    Asset,
    Branch,
    BranchAccess,
    MaintenanceLog,
    Priority,
    RequestEvent,
    RequestStatus,
    Role,
    ServiceRequest,
    User,
    WorkOrder,
    WorkStatus,
)
from app.security import current_user

router = APIRouter(prefix="/api/requests", tags=["Service requests"])


class RequestInput(BaseModel):
    branch_id: uuid.UUID
    asset_id: uuid.UUID | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=180)]
    description: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=10, max_length=10000)
    ]
    location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class RequestOutput(BaseModel):
    id: uuid.UUID
    branch_id: uuid.UUID
    branch_name: str
    submitted_by: uuid.UUID
    submitted_by_name: str
    asset_id: uuid.UUID | None
    asset_name: str | None
    title: str
    description: str
    location: str
    priority: Priority | None
    status: RequestStatus
    created_at: datetime


class EventOutput(BaseModel):
    id: uuid.UUID
    action: str
    actor_name: str
    created_at: datetime
    details: dict


class TechnicianOption(BaseModel):
    id: uuid.UUID
    full_name: str


class AssignmentInput(BaseModel):
    technician_id: uuid.UUID


class ReturnInput(AssignmentInput):
    work_order_id: uuid.UUID
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class ReassignmentInput(AssignmentInput):
    previous_technician_id: uuid.UUID
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class VerificationInput(BaseModel):
    work_order_id: uuid.UUID
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)] = ""


class WorkOrderOutput(BaseModel, from_attributes=True):
    id: uuid.UUID
    technician_id: uuid.UUID
    status: WorkStatus
    labor_cost: Decimal
    materials_cost: Decimal

    @field_serializer("labor_cost", "materials_cost", when_used="json")
    def serialize_cost(self, amount: Decimal) -> str:
        return format(amount, ".2f")


class MaintenanceLogInput(BaseModel):
    action: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]
    notes: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class MaintenanceLogOutput(BaseModel):
    id: uuid.UUID
    work_order_id: uuid.UUID
    recorded_by_name: str
    created_at: datetime
    action: str
    notes: str


Money = Annotated[Decimal, Field(ge=0, le=Decimal("9999999999.99"), decimal_places=2)]


class CompletionInput(BaseModel):
    labor_cost: Money
    materials_cost: Money


class DetailOutput(RequestOutput):
    events: list[EventOutput]
    eligible_technicians: list[TechnicianOption] | None = None
    work_orders: list[WorkOrderOutput]
    maintenance_logs: list[MaintenanceLogOutput]


class PriorityInput(BaseModel):
    priority: Priority


def visible(user: User, db: Session):
    query = select(ServiceRequest).where(ServiceRequest.branch_id.in_(branch_ids(db, user.id)))
    if user.role == Role.branch_manager:
        query = query.where(ServiceRequest.submitted_by == user.id)
    elif user.role == Role.technician:
        query = query.where(
            ServiceRequest.id.in_(
                select(WorkOrder.request_id).where(WorkOrder.technician_id == user.id)
            )
        )
    return query


def output(request: ServiceRequest, db: Session) -> dict:
    asset = db.get(Asset, request.asset_id) if request.asset_id else None
    return {
        field: getattr(request, field)
        for field in RequestOutput.model_fields
        if field not in {"branch_name", "submitted_by_name", "asset_name"}
    } | {
        "branch_name": db.get(Branch, request.branch_id).name,
        "submitted_by_name": db.get(User, request.submitted_by).full_name,
        "asset_name": f"{asset.asset_tag} · {asset.name}" if asset else None,
    }


def eligible_technicians(branch_id: uuid.UUID):
    return (
        select(User)
        .join(BranchAccess, BranchAccess.user_id == User.id)
        .where(BranchAccess.branch_id == branch_id, User.role == Role.technician, User.is_active)
    )


def can_assign(request: ServiceRequest, db: Session) -> bool:
    return (
        request.status == RequestStatus.submitted
        and db.scalar(select(WorkOrder.id).where(WorkOrder.request_id == request.id).limit(1))
        is None
    )


@router.post("", response_model=RequestOutput, status_code=201)
def submit(data: RequestInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != Role.branch_manager:
        raise HTTPException(403, "Only branch managers can submit service requests")
    if data.branch_id not in branch_ids(db, user.id):
        raise HTTPException(403, "You do not have access to this branch")
    if data.asset_id:
        asset = db.get(Asset, data.asset_id)
        if asset is None or asset.branch_id != data.branch_id:
            raise HTTPException(422, "Select an asset belonging to this branch")
    request = ServiceRequest(**data.model_dump(), submitted_by=user.id)
    db.add(request)
    db.flush()
    db.add(
        RequestEvent(
            request_id=request.id,
            actor_id=user.id,
            action="submitted",
            details={"status": "submitted"},
        )
    )
    db.commit()
    return output(request, db)


@router.get("", response_model=list[RequestOutput])
def list_requests(
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    branch_id: uuid.UUID | None = None,
    status: RequestStatus | None = None,
    priority: Priority | None = None,
    search: str = Query(default="", max_length=180),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
):
    query = visible(user, db)
    if branch_id:
        query = query.where(ServiceRequest.branch_id == branch_id)
    if status:
        query = query.where(ServiceRequest.status == status)
    if priority:
        query = query.where(ServiceRequest.priority == priority)
    if search.strip():
        query = query.where(ServiceRequest.title.icontains(search.strip(), autoescape=True))
    query = query.order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
    return [output(request, db) for request in db.scalars(query.offset(offset).limit(limit))]


@router.get("/assets")
def assets(branch_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if branch_id not in branch_ids(db, user.id):
        raise HTTPException(403, "You do not have access to this branch")
    return [
        {"id": asset.id, "name": asset.name, "asset_tag": asset.asset_tag}
        for asset in db.scalars(
            select(Asset).where(Asset.branch_id == branch_id).order_by(Asset.name)
        )
    ]


@router.get("/{request_id}", response_model=DetailOutput)
def detail(
    request_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id))
    if request is None:
        raise HTTPException(404, "Service request not found")
    events = db.execute(
        select(RequestEvent, User.full_name)
        .join(User, User.id == RequestEvent.actor_id)
        .where(RequestEvent.request_id == request.id)
        .order_by(RequestEvent.created_at, RequestEvent.id)
    ).all()
    technicians = None
    if user.role == Role.administrator and request.status != RequestStatus.closed:
        technicians = [
            TechnicianOption(id=technician.id, full_name=technician.full_name)
            for technician in db.scalars(
                eligible_technicians(request.branch_id).order_by(User.full_name, User.id)
            )
        ]
    work_orders = []
    orders = select(WorkOrder).where(WorkOrder.request_id == request.id)
    if user.role == Role.technician:
        orders = orders.where(WorkOrder.technician_id == user.id)
    if user.role in (Role.administrator, Role.technician):
        work_orders = db.scalars(orders.order_by(WorkOrder.created_at, WorkOrder.id)).all()
    maintenance_logs = [
        log_output(log, name)
        for log, name in db.execute(
            select(MaintenanceLog, User.full_name)
            .join(User, User.id == MaintenanceLog.recorded_by)
            .where(MaintenanceLog.work_order_id.in_(orders.with_only_columns(WorkOrder.id)))
            .order_by(MaintenanceLog.created_at, MaintenanceLog.id)
        )
    ]
    return output(request, db) | {
        "eligible_technicians": technicians,
        "work_orders": work_orders,
        "maintenance_logs": maintenance_logs,
        "events": [
            EventOutput(
                id=event.id,
                action=event.action,
                actor_name=name,
                created_at=event.created_at,
                details=event.details,
            )
            for event, name in events
        ],
    }


@router.post("/{request_id}/work-orders", response_model=WorkOrderOutput, status_code=201)
def assign_work_order(
    request_id: uuid.UUID,
    data: AssignmentInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Service request not found")
    if not can_assign(request, db):
        raise HTTPException(409, "Only submitted requests without a work order can be assigned")
    work_order, technician = create_assignment(request, data.technician_id, user, db)
    db.add(
        RequestEvent(
            request_id=request.id,
            actor_id=user.id,
            action="work_order_assigned",
            details={
                "work_order_id": str(work_order.id),
                "technician_name": technician.full_name,
                "technician_id": str(technician.id),
            },
        )
    )
    result = WorkOrderOutput.model_validate(work_order)
    db.commit()
    return result


def create_assignment(
    request: ServiceRequest, technician_id: uuid.UUID, actor: User, db: Session
) -> tuple[WorkOrder, User]:
    technician = lock_eligible_technician(request.branch_id, technician_id, db)
    work_order = WorkOrder(
        request_id=request.id,
        technician_id=technician.id,
        assigned_by=actor.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(work_order)
    db.flush()
    return work_order, technician


def lock_eligible_technician(branch_id: uuid.UUID, technician_id: uuid.UUID, db: Session) -> User:
    technician = db.scalar(
        eligible_technicians(branch_id).where(User.id == technician_id).with_for_update()
    )
    if technician is None:
        raise HTTPException(422, "Select an active technician with access to this branch")
    return technician


@router.post("/{request_id}/work-orders/{work_order_id}/reassign", response_model=WorkOrderOutput)
def reassign_work_order(
    request_id: uuid.UUID,
    work_order_id: uuid.UUID,
    data: ReassignmentInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Work order not found")
    work_order = db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == work_order_id, WorkOrder.request_id == request.id)
        .with_for_update()
    )
    if work_order is None:
        raise HTTPException(404, "Work order not found")
    if request.status not in (RequestStatus.submitted, RequestStatus.in_progress) or (
        work_order.status not in (WorkStatus.assigned, WorkStatus.in_progress)
    ):
        raise HTTPException(409, "Only active work orders can be reassigned")
    if work_order.technician_id != data.previous_technician_id:
        raise HTTPException(409, "The assignment changed. Refresh the request and try again")
    if data.technician_id == work_order.technician_id:
        raise HTTPException(422, "Select a different technician")

    previous = db.get(User, work_order.technician_id)
    technician = lock_eligible_technician(request.branch_id, data.technician_id, db)
    work_order.technician_id = technician.id
    db.add(
        RequestEvent(
            request_id=request.id,
            actor_id=user.id,
            action="work_reassigned",
            details={
                "work_order_id": str(work_order.id),
                "previous_technician_id": str(previous.id),
                "previous_technician_name": previous.full_name,
                "technician_id": str(technician.id),
                "technician_name": technician.full_name,
                "reason": data.reason,
            },
        )
    )
    result = WorkOrderOutput.model_validate(work_order)
    db.commit()
    return result


def request_for_review(
    request_id: uuid.UUID, work_order_id: uuid.UUID, user: User, db: Session
) -> ServiceRequest:
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Service request not found")
    if request.status != RequestStatus.awaiting_verification:
        raise HTTPException(409, "Only requests awaiting verification can be reviewed")
    latest_order = db.scalar(
        select(WorkOrder)
        .where(WorkOrder.request_id == request.id)
        .order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
        .limit(1)
    )
    if (
        latest_order is None
        or latest_order.id != work_order_id
        or latest_order.status != WorkStatus.completed
    ):
        raise HTTPException(409, "Refresh the request and review the latest completed work order")
    return request


@router.post("/{request_id}/return", response_model=WorkOrderOutput, status_code=201)
def return_for_follow_up(
    request_id: uuid.UUID,
    data: ReturnInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request = request_for_review(request_id, data.work_order_id, user, db)
    work_order, technician = create_assignment(request, data.technician_id, user, db)
    request.status = RequestStatus.in_progress
    db.add(
        RequestEvent(
            request_id=request.id,
            actor_id=user.id,
            action="work_returned",
            details={
                "work_order_id": str(work_order.id),
                "reviewed_work_order_id": str(data.work_order_id),
                "technician_name": technician.full_name,
                "technician_id": str(technician.id),
                "reason": data.reason,
            },
        )
    )
    result = WorkOrderOutput.model_validate(work_order)
    db.commit()
    return result


@router.post("/{request_id}/verify", response_model=RequestOutput)
def verify_and_close(
    request_id: uuid.UUID,
    data: VerificationInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request = request_for_review(request_id, data.work_order_id, user, db)
    request.status = RequestStatus.closed
    request.closed_by = user.id
    request.closed_at = datetime.now(timezone.utc)
    db.add(
        RequestEvent(
            request_id=request.id,
            actor_id=user.id,
            action="verified_and_closed",
            details={"work_order_id": str(data.work_order_id), "notes": data.notes},
        )
    )
    db.commit()
    return output(request, db)


def assigned_work(
    request_id: uuid.UUID, work_order_id: uuid.UUID, user: User, db: Session
) -> tuple[ServiceRequest, WorkOrder]:
    if user.role != Role.technician:
        raise HTTPException(403, "Only technicians can update work orders")
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Work order not found")
    work_order = db.scalar(
        select(WorkOrder)
        .where(
            WorkOrder.id == work_order_id,
            WorkOrder.request_id == request.id,
            WorkOrder.technician_id == user.id,
        )
        .with_for_update()
    )
    if work_order is None:
        raise HTTPException(404, "Work order not found")
    return request, work_order


@router.post("/{request_id}/work-orders/{work_order_id}/start", response_model=WorkOrderOutput)
def start_work_order(
    request_id: uuid.UUID,
    work_order_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    request, work_order = assigned_work(request_id, work_order_id, user, db)
    if request.status == RequestStatus.in_progress and work_order.status == WorkStatus.in_progress:
        return work_order
    if (
        request.status not in (RequestStatus.submitted, RequestStatus.in_progress)
        or work_order.status != WorkStatus.assigned
    ):
        raise HTTPException(409, "Only assigned work on an active request can be started")

    request.status = RequestStatus.in_progress
    work_order.status = WorkStatus.in_progress
    db.add(
        RequestEvent(
            request_id=request.id,
            actor_id=user.id,
            action="work_started",
            details={"work_order_id": str(work_order.id)},
        )
    )
    result = WorkOrderOutput.model_validate(work_order)
    db.commit()
    return result


def log_output(log: MaintenanceLog, name: str) -> MaintenanceLogOutput:
    return MaintenanceLogOutput(
        id=log.id,
        work_order_id=log.work_order_id,
        recorded_by_name=name,
        created_at=log.created_at,
        action=log.action,
        notes=log.notes,
    )


def require_in_progress(request: ServiceRequest, work_order: WorkOrder):
    if request.status != RequestStatus.in_progress or work_order.status != WorkStatus.in_progress:
        raise HTTPException(409, "Work must be in progress")


@router.post("/{request_id}/work-orders/{work_order_id}/logs", status_code=201)
def add_maintenance_log(
    request_id: uuid.UUID,
    work_order_id: uuid.UUID,
    data: MaintenanceLogInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> MaintenanceLogOutput:
    request, work_order = assigned_work(request_id, work_order_id, user, db)
    require_in_progress(request, work_order)
    log = MaintenanceLog(work_order_id=work_order.id, recorded_by=user.id, **data.model_dump())
    db.add(log)
    db.flush()
    db.add(
        RequestEvent(
            request_id=request.id,
            actor_id=user.id,
            action="maintenance_logged",
            details={"work_order_id": str(work_order.id)},
        )
    )
    result = log_output(log, user.full_name)
    db.commit()
    return result


@router.post("/{request_id}/work-orders/{work_order_id}/complete", response_model=WorkOrderOutput)
def complete_work_order(
    request_id: uuid.UUID,
    work_order_id: uuid.UUID,
    data: CompletionInput,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    request, work_order = assigned_work(request_id, work_order_id, user, db)
    if work_order.status == WorkStatus.completed:
        if (work_order.labor_cost, work_order.materials_cost) == (
            data.labor_cost,
            data.materials_cost,
        ):
            return work_order
        raise HTTPException(409, "This work order has already been completed")
    require_in_progress(request, work_order)
    work_order.labor_cost = data.labor_cost
    work_order.materials_cost = data.materials_cost
    work_order.status = WorkStatus.completed
    request.status = RequestStatus.awaiting_verification
    db.add(
        RequestEvent(
            request_id=request.id,
            actor_id=user.id,
            action="work_completed",
            details={"work_order_id": str(work_order.id)},
        )
    )
    result = WorkOrderOutput.model_validate(work_order)
    db.commit()
    return result


@router.patch("/{request_id}/priority", response_model=RequestOutput)
def set_priority(
    request_id: uuid.UUID,
    data: PriorityInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Service request not found")
    if request.status == RequestStatus.closed:
        raise HTTPException(409, "Closed requests cannot be reprioritized")
    if request.priority != data.priority:
        previous = request.priority
        request.priority = data.priority
        db.add(
            RequestEvent(
                request_id=request.id,
                actor_id=user.id,
                action="priority_changed",
                details={"from": previous, "to": data.priority},
            )
        )
    db.commit()
    return output(request, db)
