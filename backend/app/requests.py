import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import (
    AwareDatetime,
    BaseModel,
    Field,
    StringConstraints,
    field_serializer,
    model_validator,
)
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.admin import administrator, branch_ids
from app.db import get_db
from app.models import (
    Asset,
    Attachment,
    Branch,
    BranchAccess,
    Difficulty,
    MaintenanceLog,
    Priority,
    RequestEvent,
    RequestIntake,
    RequestStatus,
    Role,
    ServiceCategory,
    ServiceRequest,
    User,
    WorkOrder,
    WorkOrderAssistant,
    WorkStatus,
)
from app.security import current_user

router = APIRouter(prefix="/api/requests", tags=["Service requests"])

# Minutes for easy, moderate, and hard requests, respectively.
SUGGESTED_MINUTES = {
    "electrical": (30, 75, 150),
    "plumbing": (30, 60, 120),
    "air-conditioning-ventilation": (45, 90, 180),
    "it-network": (30, 60, 120),
    "equipment-repair": (45, 90, 180),
    "building-facilities": (45, 120, 240),
    "other": (30, 60, 120),
}


def duration_suggestions(category_id: str | None) -> dict[Difficulty, int]:
    minutes = SUGGESTED_MINUTES.get(category_id or "")
    return dict(zip(Difficulty, minutes, strict=True)) if minutes else {}


class QueueFocus(StrEnum):
    needs_assignment = "needs_assignment"
    urgent_open = "urgent_open"
    work_in_progress = "work_in_progress"
    awaiting_verification = "awaiting_verification"


def queue_conditions():
    orders = select(WorkOrder.id).where(WorkOrder.request_id == ServiceRequest.id)
    return {
        QueueFocus.needs_assignment: (ServiceRequest.status == RequestStatus.submitted)
        & ~orders.exists(),
        QueueFocus.urgent_open: (ServiceRequest.priority == Priority.urgent)
        & (ServiceRequest.status != RequestStatus.closed),
        QueueFocus.work_in_progress: (ServiceRequest.status == RequestStatus.in_progress)
        & orders.where(WorkOrder.status == WorkStatus.in_progress).exists(),
        QueueFocus.awaiting_verification: ServiceRequest.status
        == RequestStatus.awaiting_verification,
    }


class RequestInput(BaseModel):
    branch_id: uuid.UUID
    asset_id: uuid.UUID | None = None
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=180)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=10000)]
    location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    category_id: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None = None
    priority: Priority | None = None
    triage_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def nonblank_description(self):
        if not self.description.strip():
            raise ValueError("Describe the issue")
        return self


class CategoryOutput(BaseModel, from_attributes=True):
    id: str
    name: str


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
    category: CategoryOutput | None
    difficulty: Difficulty | None
    duration_override_minutes: int | None
    suggested_duration_minutes: int | None
    estimated_duration_minutes: int | None
    status: RequestStatus
    setup_missing: list[str] | None = None
    intake: dict | None = None
    safety_flags: list[str] = Field(default_factory=list)
    incomplete_info: bool = False
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
    specialization: str | None
    matches_category: bool


class AssignmentInput(BaseModel):
    technician_id: uuid.UUID
    assistant_ids: list[uuid.UUID] = Field(default_factory=list)


class ReturnInput(AssignmentInput):
    work_order_id: uuid.UUID
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class ReassignmentInput(BaseModel):
    technician_id: uuid.UUID
    previous_technician_id: uuid.UUID
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=10000)]


class VerificationInput(BaseModel):
    work_order_id: uuid.UUID
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)] = ""


class TeamInput(BaseModel):
    assistant_ids: list[uuid.UUID]


class ScheduleInput(BaseModel):
    scheduled_start: AwareDatetime | None
    duration_minutes: Annotated[int, Field(strict=True, ge=1, le=10080)] | None = None


class TechnicianName(BaseModel, from_attributes=True):
    id: uuid.UUID
    full_name: str


class WorkSchedule(BaseModel, from_attributes=True):
    scheduled_start: datetime | None
    scheduled_end: datetime | None

    @field_serializer("scheduled_start", "scheduled_end", when_used="json")
    def serialize_time(self, value: datetime | None) -> str | None:
        return value.replace(tzinfo=value.tzinfo or timezone.utc).isoformat() if value else None


class WorkOrderOutput(WorkSchedule):
    id: uuid.UUID
    technician_id: uuid.UUID
    status: WorkStatus
    labor_cost: Decimal
    materials_cost: Decimal
    lead: TechnicianName
    assistants: list[TechnicianName]
    price_estimate: dict | None
    approved_price: dict | None
    overrun_reason: str | None

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


class MaterialInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=180)]
    quantity: Annotated[Decimal, Field(gt=0, le=1000000, decimal_places=3)]
    unit_price: Money
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class PriceInput(BaseModel):
    hourly_rate: Money
    materials_estimate: Money = Decimal("0")
    materials_items: Annotated[list[MaterialInput], Field(max_length=100)] | None = None
    override: Money | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)] = ""


class CompletionInput(BaseModel):
    labor_cost: Money
    materials_cost: Money
    overrun_reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)] = ""


class PriceApprovalInput(BaseModel):
    version: Annotated[int, Field(strict=True, ge=0)]


class PhotoOutput(BaseModel, from_attributes=True):
    id: uuid.UUID
    original_name: str
    work_order_id: uuid.UUID | None


class DetailOutput(RequestOutput):
    appointment: WorkSchedule | None
    duration_suggestions: dict[Difficulty, int]
    setup_duration_suggestions: dict[str, dict[Difficulty, int]] | None = None
    events: list[EventOutput]
    eligible_technicians: list[TechnicianOption] | None = None
    work_orders: list[WorkOrderOutput]
    maintenance_logs: list[MaintenanceLogOutput]
    photos: list[PhotoOutput]


class PriorityInput(BaseModel):
    priority: Priority


class CategoryInput(BaseModel):
    category_id: Annotated[str, StringConstraints(min_length=1, max_length=50)] | None


class EstimateInput(BaseModel):
    difficulty: Difficulty | None
    duration_override_minutes: Annotated[int, Field(strict=True, ge=1, le=10080)] | None


class SetupTeam(AssignmentInput):
    previous_technician_id: uuid.UUID | None = None
    reason: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10000)] = ""


class RequestSetupInput(BaseModel):
    priority: Priority | None = None
    category: CategoryInput | None = None
    estimate: EstimateInput | None = None
    work_order_id: uuid.UUID | None = None
    team: SetupTeam | None = None
    schedule: ScheduleInput | None = None
    price: PriceInput | None = None


def assigned_to(technician_id: uuid.UUID):
    return or_(
        WorkOrder.technician_id == technician_id,
        select(WorkOrderAssistant.work_order_id)
        .where(
            WorkOrderAssistant.work_order_id == WorkOrder.id,
            WorkOrderAssistant.technician_id == technician_id,
        )
        .exists(),
    )


def visible(user: User, db: Session):
    query = select(ServiceRequest).where(ServiceRequest.branch_id.in_(branch_ids(db, user.id)))
    if user.role == Role.branch_manager:
        query = query.where(ServiceRequest.submitted_by == user.id)
    elif user.role == Role.technician:
        query = query.where(
            ServiceRequest.id.in_(select(WorkOrder.request_id).where(assigned_to(user.id)))
        )
    return query


def suggested_duration(request: ServiceRequest) -> int | None:
    return (
        duration_suggestions(request.category_id).get(request.difficulty)
        if request.difficulty
        else None
    )


def setup_missing(request: ServiceRequest, order: WorkOrder | None) -> list[str]:
    if request.status not in (RequestStatus.submitted, RequestStatus.in_progress):
        return []
    return [
        label
        for label, missing in (
            ("Priority", request.priority is None),
            ("Category", request.category_id is None),
            ("Difficulty", request.difficulty is None),
            (
                "Service duration",
                request.duration_override_minutes is None and suggested_duration(request) is None,
            ),
            ("Lead technician", order is None),
            ("Schedule", order is None or order.scheduled_start is None),
            ("Price estimate", order is None or order.price_estimate is None),
        )
        if missing
    ]


def output(request: ServiceRequest, db: Session) -> dict:
    from app.intake import intake_output

    intake = intake_output(request, db)
    asset = db.get(Asset, request.asset_id) if request.asset_id else None
    suggested = suggested_duration(request)
    return {
        field: getattr(request, field)
        for field in RequestOutput.model_fields
        if field
        not in {
            "branch_name",
            "submitted_by_name",
            "asset_name",
            "suggested_duration_minutes",
            "estimated_duration_minutes",
            "setup_missing",
            "intake",
            "safety_flags",
            "incomplete_info",
        }
    } | {
        "branch_name": db.get(Branch, request.branch_id).name,
        "submitted_by_name": db.get(User, request.submitted_by).full_name,
        "asset_name": f"{asset.asset_tag} · {asset.name}" if asset else None,
        "suggested_duration_minutes": suggested,
        "estimated_duration_minutes": request.duration_override_minutes or suggested,
        "intake": intake,
        "safety_flags": intake["ai_safety_flags"] if intake else [],
        "incomplete_info": intake["incomplete_info"] if intake else False,
    }


def eligible_technicians(branch_id: uuid.UUID):
    return (
        select(User)
        .join(BranchAccess, BranchAccess.user_id == User.id)
        .where(BranchAccess.branch_id == branch_id, User.role == Role.technician, User.is_active)
    )


def technician_options(request: ServiceRequest, db: Session) -> list[TechnicianOption]:
    technicians = list(
        db.scalars(eligible_technicians(request.branch_id).order_by(User.full_name, User.id))
    )
    categories = {}
    if any(technician.specialization for technician in technicians):
        for category in db.scalars(select(ServiceCategory)):
            categories[category.id] = category
            categories[category.name.casefold()] = category
    options = []
    for technician in technicians:
        value = technician.specialization
        category = categories.get((value or "").strip().casefold())
        options.append(
            TechnicianOption(
                id=technician.id,
                full_name=technician.full_name,
                specialization=category.name if category else value,
                matches_category=category is not None and category.id == request.category_id,
            )
        )
    return sorted(options, key=lambda option: not option.matches_category)


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
    if data.category_id is not None and db.get(ServiceCategory, data.category_id) is None:
        raise HTTPException(422, "Select an available service category")
    request = ServiceRequest(
        **(
            data.model_dump(exclude={"triage_id"})
            | {
                "description": data.description.strip(),
            }
        ),
        submitted_by=user.id,
    )
    db.add(request)
    db.flush()
    from app.intake import attach_intake

    try:
        attach_intake(request, data, user, db)
    except HTTPException:
        db.rollback()
        raise
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
    category_id: Annotated[str | None, Query(min_length=1, max_length=50)] = None,
    ai_overridden: bool | None = None,
    focus: QueueFocus | None = None,
    search: str = Query(default="", max_length=180),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=25, ge=1, le=100),
):
    query = visible(user, db).options(selectinload(ServiceRequest.category))
    if ai_overridden is not None:
        query = query.where(
            select(RequestIntake.id)
            .where(
                RequestIntake.request_id == ServiceRequest.id,
                RequestIntake.ai_overridden == ai_overridden,
            )
            .exists()
        )
    if focus:
        query = query.where(queue_conditions()[focus])
    if branch_id:
        query = query.where(ServiceRequest.branch_id == branch_id)
    if status:
        query = query.where(ServiceRequest.status == status)
    if priority:
        query = query.where(ServiceRequest.priority == priority)
    if category_id == "uncategorized":
        query = query.where(ServiceRequest.category_id.is_(None))
    elif category_id is not None:
        query = query.where(ServiceRequest.category_id == category_id)
    if search.strip():
        query = query.where(ServiceRequest.title.icontains(search.strip(), autoescape=True))
    query = query.order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
    requests = list(db.scalars(query.offset(offset).limit(limit)))
    if user.role != Role.administrator or not requests:
        return [output(request, db) for request in requests]
    orders = {
        order.request_id: order
        for order in db.scalars(
            select(WorkOrder).where(
                WorkOrder.request_id.in_([request.id for request in requests]),
                WorkOrder.status.in_((WorkStatus.assigned, WorkStatus.in_progress)),
            )
        )
    }
    return [
        output(request, db) | {"setup_missing": setup_missing(request, orders.get(request.id))}
        for request in requests
    ]


@router.get("/dashboard", response_model=dict[QueueFocus, int])
def dashboard(
    branch_id: uuid.UUID | None = None,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    scoped = visible(user, db)
    if branch_id is not None:
        scoped = scoped.where(ServiceRequest.branch_id == branch_id)
    counts = [
        func.count().filter(condition).label(focus.value)
        for focus, condition in queue_conditions().items()
    ]
    return dict(
        db.execute(scoped.with_only_columns(*counts, maintain_column_froms=True)).mappings().one()
    )


@router.get("/categories", response_model=list[CategoryOutput])
def list_categories(_: User = Depends(administrator), db: Session = Depends(get_db)):
    return list(db.scalars(select(ServiceCategory).order_by(ServiceCategory.name)))


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
    event_query = (
        select(RequestEvent, User.full_name)
        .join(User, User.id == RequestEvent.actor_id)
        .where(RequestEvent.request_id == request.id)
        .order_by(RequestEvent.created_at, RequestEvent.id)
    )
    technicians = None
    if user.role == Role.administrator and request.status != RequestStatus.closed:
        technicians = technician_options(request, db)
    work_orders = []
    orders = select(WorkOrder).where(WorkOrder.request_id == request.id)
    if user.role == Role.technician:
        orders = orders.where(assigned_to(user.id))
    if user.role in (Role.administrator, Role.technician):
        work_orders = db.scalars(
            orders.options(
                selectinload(WorkOrder.lead), selectinload(WorkOrder.assistants)
            ).order_by(WorkOrder.created_at, WorkOrder.id)
        ).all()
    if user.role != Role.administrator:
        budget_visible = RequestEvent.action.not_in(("work_price_changed", "work_price_approved"))
        if user.role == Role.technician:
            budget_visible = or_(
                budget_visible,
                RequestEvent.details["work_order_id"]
                .as_string()
                .in_([str(order.id) for order in work_orders]),
            )
        event_query = event_query.where(budget_visible)
    appointment = None
    if user.role == Role.branch_manager:
        appointment = db.scalar(
            orders.order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc()).limit(1)
        )
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
        "appointment": appointment if appointment and appointment.scheduled_start else None,
        "duration_suggestions": duration_suggestions(request.category_id),
        "setup_duration_suggestions": (
            {category: duration_suggestions(category) for category in SUGGESTED_MINUTES}
            if technicians is not None
            else None
        ),
        "setup_missing": (
            setup_missing(
                request,
                next(
                    (
                        order
                        for order in reversed(work_orders)
                        if order.status != WorkStatus.completed
                    ),
                    None,
                ),
            )
            if user.role == Role.administrator
            else None
        ),
        "work_orders": work_orders,
        "maintenance_logs": maintenance_logs,
        "photos": db.scalars(
            select(Attachment)
            .where(Attachment.request_id == request.id, Attachment.image_data.is_not(None))
            .order_by(Attachment.created_at, Attachment.id)
        ).all(),
        "events": [
            EventOutput(
                id=event.id,
                action=event.action,
                actor_name=name,
                created_at=event.created_at,
                details=event.details,
            )
            for event, name in db.execute(event_query)
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
    work_order, technician = create_assignment(request, data, user, db)
    record_assignment(request, work_order, technician, user, db)
    result = WorkOrderOutput.model_validate(work_order)
    db.commit()
    return result


def record_assignment(
    request: ServiceRequest, work_order: WorkOrder, technician: User, user: User, db: Session
):
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


def create_assignment(
    request: ServiceRequest, data: AssignmentInput, actor: User, db: Session
) -> tuple[WorkOrder, User]:
    team = lock_eligible_team(request.branch_id, data.technician_id, data.assistant_ids, db)
    technician = team[data.technician_id]
    work_order = WorkOrder(
        request_id=request.id,
        lead=technician,
        assistants=[team[assistant_id] for assistant_id in data.assistant_ids],
        assigned_by=actor.id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(work_order)
    db.flush()
    return work_order, technician


def lock_eligible_team(
    branch_id: uuid.UUID, lead_id: uuid.UUID, assistant_ids: list[uuid.UUID], db: Session
) -> dict[uuid.UUID, User]:
    ids = {lead_id, *assistant_ids}
    if len(ids) != len(assistant_ids) + 1:
        raise HTTPException(422, "Select each technician only once")
    # Serialize scheduling operations across branches for shared technicians.
    db.scalars(select(User.id).where(User.id.in_(ids)).order_by(User.id).with_for_update()).all()
    team = {
        member.id: member
        for member in db.scalars(eligible_technicians(branch_id).where(User.id.in_(ids)))
    }
    if team.keys() != ids:
        raise HTTPException(422, "Select active technicians with access to this branch")
    return team


def ensure_schedule_available(
    db: Session, order: WorkOrder, team_ids: set[uuid.UUID], start: datetime, end: datetime
):
    assigned_assistants = select(WorkOrderAssistant.work_order_id).where(
        WorkOrderAssistant.technician_id.in_(team_ids)
    )
    overlapping = db.scalar(
        select(WorkOrder.id)
        .where(
            WorkOrder.id != order.id,
            WorkOrder.status.in_((WorkStatus.assigned, WorkStatus.in_progress)),
            WorkOrder.scheduled_start < end,
            WorkOrder.scheduled_end > start,
            or_(WorkOrder.technician_id.in_(team_ids), WorkOrder.id.in_(assigned_assistants)),
        )
        .limit(1)
    )
    if overlapping is not None:
        raise HTTPException(409, "A technician already has work scheduled during this time")


def editable_work_order(
    request_id: uuid.UUID, order_id: uuid.UUID, actor: User, db: Session
) -> tuple[ServiceRequest, WorkOrder]:
    request = db.scalar(visible(actor, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Work order not found")
    order = db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == order_id, WorkOrder.request_id == request.id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(404, "Work order not found")
    if order.status == WorkStatus.completed:
        raise HTTPException(409, "Completed work orders cannot be edited")
    return request, order


def record_order_change(db: Session, order: WorkOrder, actor: User, action: str, details: dict):
    db.add(
        RequestEvent(
            request_id=order.request_id,
            actor_id=actor.id,
            action=action,
            details={"work_order_id": str(order.id), **details},
        )
    )


@router.patch("/{request_id}/work-orders/{order_id}/team", response_model=WorkOrderOutput)
def update_work_team(
    request_id: uuid.UUID,
    order_id: uuid.UUID,
    data: TeamInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request, order = editable_work_order(request_id, order_id, user, db)
    team = lock_eligible_team(request.branch_id, order.technician_id, data.assistant_ids, db)
    if set(data.assistant_ids) == {member.id for member in order.assistants}:
        return order
    if order.scheduled_start is not None:
        ensure_schedule_available(db, order, set(team), order.scheduled_start, order.scheduled_end)
    record_team(order, [team[member_id] for member_id in data.assistant_ids], user, db)
    db.commit()
    return order


def record_team(order: WorkOrder, assistants: list[User], user: User, db: Session):
    if {member.id for member in order.assistants} == {member.id for member in assistants}:
        return
    previous = [member.full_name for member in order.assistants]
    order.assistants = sorted(assistants, key=lambda member: (member.full_name, member.id))
    record_order_change(
        db,
        order,
        user,
        "work_team_changed",
        {"before": previous, "assistants": [member.full_name for member in order.assistants]},
    )


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


@router.patch("/{request_id}/work-orders/{order_id}/schedule", response_model=WorkOrderOutput)
def update_work_schedule(
    request_id: uuid.UUID,
    order_id: uuid.UUID,
    data: ScheduleInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request, order = editable_work_order(request_id, order_id, user, db)
    start, end = planned_slot(request, data)
    if start is not None:
        team = lock_eligible_team(
            request.branch_id, order.technician_id, [member.id for member in order.assistants], db
        )
        ensure_schedule_available(db, order, set(team), start, end)
    if record_schedule(order, start, end, user, db):
        db.commit()
    return order


def planned_slot(
    request: ServiceRequest, data: ScheduleInput
) -> tuple[datetime | None, datetime | None]:
    if data.scheduled_start is None:
        if data.duration_minutes is not None:
            raise HTTPException(422, "Select a start time for the duration")
        return None, None
    minutes = (
        data.duration_minutes or request.duration_override_minutes or suggested_duration(request)
    )
    if minutes is None:
        raise HTTPException(422, "Enter a scheduled duration or save a service estimate first")
    try:
        start = as_utc(data.scheduled_start)
        end = start + timedelta(minutes=minutes)
    except OverflowError:
        raise HTTPException(422, "Select a valid schedule date") from None
    if start < datetime.now(timezone.utc):
        raise HTTPException(422, "Choose a planned start time in the future")
    return start, end


def record_schedule(
    order: WorkOrder, start: datetime | None, end: datetime | None, user: User, db: Session
) -> bool:
    previous = WorkSchedule.model_validate(order).model_dump(mode="json")
    if (start, end) == tuple(
        as_utc(value) if value else None for value in (order.scheduled_start, order.scheduled_end)
    ):
        return False
    order.scheduled_start, order.scheduled_end = start, end
    record_order_change(
        db,
        order,
        user,
        "work_schedule_changed",
        {
            "previous_schedule": previous,
            **WorkSchedule.model_validate(order).model_dump(mode="json"),
        },
    )
    return True


@router.patch("/{request_id}/work-orders/{order_id}/price", response_model=WorkOrderOutput)
def update_work_price(
    request_id: uuid.UUID,
    order_id: uuid.UUID,
    data: PriceInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request, order = editable_work_order(request_id, order_id, user, db)
    if record_price(request, order, data, user, db):
        db.commit()
    return order


def record_price(
    request: ServiceRequest, order: WorkOrder, data: PriceInput, user: User, db: Session
) -> bool:
    if data.override is not None and not data.reason:
        raise HTTPException(422, "Enter a reason for overriding the suggested price")
    minutes = request.duration_override_minutes or suggested_duration(request)
    if order.scheduled_start is not None:
        minutes = int((order.scheduled_end - order.scheduled_start).total_seconds() // 60)
    if minutes is None:
        raise HTTPException(422, "Set a schedule or estimated service duration first")
    team_size = 1 + len(order.assistants)
    labor = (data.hourly_rate * minutes * team_size / 60).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    items = None
    materials = data.materials_estimate
    if data.materials_items is not None:
        items = [
            {
                "name": item.name,
                "quantity": str(item.quantity),
                "unit_price": format(item.unit_price, ".2f"),
                "source": item.source,
                "total": format(
                    (item.quantity * item.unit_price).quantize(
                        Decimal("0.01"), rounding=ROUND_HALF_UP
                    ),
                    ".2f",
                ),
            }
            for item in data.materials_items
        ]
        materials = sum((Decimal(item["total"]) for item in items), Decimal("0"))
    suggested = labor + materials
    if suggested > Decimal("9999999999.99"):
        raise HTTPException(422, "The suggested price exceeds the supported amount")
    amount = data.override if data.override is not None else suggested
    quote = {
        "duration_minutes": minutes,
        "team_size": team_size,
        "hourly_rate": format(data.hourly_rate, ".2f"),
        "materials_estimate": format(materials, ".2f"),
        "materials_items": items,
        "labor_estimate": format(labor, ".2f"),
        "suggested": format(suggested, ".2f"),
        "amount": format(amount, ".2f"),
        "override": format(data.override, ".2f") if data.override is not None else None,
        "reason": data.reason if data.override is not None else "",
    }
    previous = order.price_estimate
    if previous and quote == {key: value for key, value in previous.items() if key != "version"}:
        return False
    quote["version"] = (previous or {}).get("version", 0) + 1
    order.price_estimate = quote
    record_order_change(
        db, order, user, "work_price_changed", {"previous_price": previous, "price": quote}
    )
    return True


@router.post("/{request_id}/work-orders/{order_id}/price/approve", response_model=WorkOrderOutput)
def approve_work_price(
    request_id: uuid.UUID,
    order_id: uuid.UUID,
    data: PriceApprovalInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    _, order = editable_work_order(request_id, order_id, user, db)
    quote = order.price_estimate
    if quote is None:
        raise HTTPException(409, "Save a price estimate before approving it")
    if quote.get("version", 0) != data.version:
        raise HTTPException(
            409, "The estimate has changed. Review the latest version before approving"
        )
    if order.approved_price and order.approved_price["quote"] == quote:
        return order
    approval = {
        "quote": quote,
        "approved_by": str(user.id),
        "approved_by_name": user.full_name,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    previous = order.approved_price
    order.approved_price = approval
    record_order_change(
        db,
        order,
        user,
        "work_price_approved",
        {"previous_approval": previous, "approval": approval},
    )
    db.commit()
    return order


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
    assistant_ids = [
        member.id for member in work_order.assistants if member.id != data.technician_id
    ]
    team = lock_eligible_team(request.branch_id, data.technician_id, assistant_ids, db)
    if work_order.scheduled_start is not None:
        ensure_schedule_available(
            db, work_order, set(team), work_order.scheduled_start, work_order.scheduled_end
        )
    technician = team[data.technician_id]
    work_order.lead = technician
    work_order.assistants = [team[assistant_id] for assistant_id in assistant_ids]
    record_reassignment(work_order, previous, technician, data.reason, user, db)
    db.flush()
    result = WorkOrderOutput.model_validate(work_order)
    db.commit()
    return result


def record_reassignment(
    order: WorkOrder, previous: User, technician: User, reason: str, actor: User, db: Session
):
    record_order_change(
        db,
        order,
        actor,
        "work_reassigned",
        {
            "previous_technician_id": str(previous.id),
            "previous_technician_name": previous.full_name,
            "technician_id": str(technician.id),
            "technician_name": technician.full_name,
            "reason": reason,
        },
    )


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
    work_order, technician = create_assignment(request, data, user, db)
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
            assigned_to(user.id),
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
    require_lead(work_order, user)
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


def require_lead(work_order: WorkOrder, user: User):
    if work_order.technician_id != user.id:
        raise HTTPException(403, "Only the lead technician can start or complete this work order")


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
    require_lead(work_order, user)
    if work_order.status == WorkStatus.completed:
        if (work_order.labor_cost, work_order.materials_cost) == (
            data.labor_cost,
            data.materials_cost,
        ) and (work_order.overrun_reason or "") == data.overrun_reason:
            return work_order
        raise HTTPException(409, "This work order has already been completed")
    require_in_progress(request, work_order)
    if (
        work_order.approved_price
        and data.labor_cost + data.materials_cost
        > Decimal(work_order.approved_price["quote"]["amount"])
        and not data.overrun_reason
    ):
        raise HTTPException(422, "Explain why actual costs exceed the approved estimate")
    work_order.labor_cost = data.labor_cost
    work_order.materials_cost = data.materials_cost
    work_order.overrun_reason = data.overrun_reason or None
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
    apply_priority(request, data, user, db)
    db.commit()
    return output(request, db)


def require_not_awaiting_verification(request: ServiceRequest):
    if request.status == RequestStatus.awaiting_verification:
        raise HTTPException(
            409,
            "Job details are locked while awaiting verification. "
            "Return the repair for follow-up to make changes.",
        )


def apply_priority(request: ServiceRequest, data: PriorityInput, user: User, db: Session):
    from app.intake import sync_confirmation

    require_not_awaiting_verification(request)
    if request.priority != data.priority:
        previous = request.priority
        request.priority = data.priority
        sync_confirmation(request, db)
        db.add(
            RequestEvent(
                request_id=request.id,
                actor_id=user.id,
                action="priority_changed",
                details={"from": previous, "to": data.priority},
            )
        )


@router.patch("/{request_id}/category", response_model=RequestOutput)
def set_category(
    request_id: uuid.UUID,
    data: CategoryInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Service request not found")
    if request.status == RequestStatus.closed:
        raise HTTPException(409, "Closed requests cannot be recategorized")
    apply_category(request, data, user, db)
    db.commit()
    return output(request, db)


def apply_category(request: ServiceRequest, data: CategoryInput, user: User, db: Session):
    from app.intake import sync_confirmation

    require_not_awaiting_verification(request)
    category = db.get(ServiceCategory, data.category_id) if data.category_id is not None else None
    if data.category_id is not None and category is None:
        raise HTTPException(422, "Select a valid service category")
    if request.category_id != data.category_id:
        previous = request.category
        request.category = category
        sync_confirmation(request, db)
        db.add(
            RequestEvent(
                request_id=request.id,
                actor_id=user.id,
                action="category_changed",
                details={
                    "from": previous.name if previous else None,
                    "to": category.name if category else None,
                },
            )
        )


@router.patch("/{request_id}/estimate", response_model=RequestOutput)
def set_estimate(
    request_id: uuid.UUID,
    data: EstimateInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Service request not found")
    if request.status == RequestStatus.closed:
        raise HTTPException(409, "Closed request estimates cannot be changed")

    apply_estimate(request, data, user, db)
    db.commit()
    return output(request, db)


def apply_estimate(request: ServiceRequest, data: EstimateInput, user: User, db: Session):
    require_not_awaiting_verification(request)
    previous = {
        "difficulty": request.difficulty,
        "duration_override_minutes": request.duration_override_minutes,
    }
    updated = data.model_dump()
    if previous != updated:
        request.difficulty = data.difficulty
        request.duration_override_minutes = data.duration_override_minutes
        db.add(
            RequestEvent(
                request_id=request.id,
                actor_id=user.id,
                action="estimate_changed",
                details={"previous": previous, "updated": updated},
            )
        )


@router.patch("/{request_id}/setup", response_model=RequestOutput)
def update_request_setup(
    request_id: uuid.UUID,
    data: RequestSetupInput,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    request = db.scalar(visible(user, db).where(ServiceRequest.id == request_id).with_for_update())
    if request is None:
        raise HTTPException(404, "Service request not found")
    if request.status == RequestStatus.closed:
        raise HTTPException(409, "Closed requests cannot be edited")
    require_not_awaiting_verification(request)
    try:
        if data.priority is not None:
            apply_priority(request, PriorityInput(priority=data.priority), user, db)
        if data.category is not None:
            apply_category(request, data.category, user, db)
        if data.estimate is not None:
            apply_estimate(request, data.estimate, user, db)
        if data.team is not None or data.schedule is not None or data.price is not None:
            db.flush()
            apply_work_setup(request, data, user, db)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    active_order = db.scalar(
        select(WorkOrder)
        .where(
            WorkOrder.request_id == request.id,
            WorkOrder.status.in_((WorkStatus.assigned, WorkStatus.in_progress)),
        )
        .order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
        .limit(1)
    )
    return output(request, db) | {"setup_missing": setup_missing(request, active_order)}


def apply_work_setup(request: ServiceRequest, data: RequestSetupInput, user: User, db: Session):
    if request.status not in (RequestStatus.submitted, RequestStatus.in_progress):
        raise HTTPException(409, "Only active requests can be scheduled or assigned")
    team = data.team
    if data.work_order_id is None:
        if team is None:
            raise HTTPException(422, "Select a lead technician first")
        if not can_assign(request, db):
            raise HTTPException(409, "The assignment changed. Refresh the request and try again")
        order, technician = create_assignment(request, team, user, db)
        record_assignment(request, order, technician, user, db)
        team = None
    else:
        order = db.scalar(
            select(WorkOrder)
            .where(WorkOrder.id == data.work_order_id, WorkOrder.request_id == request.id)
            .with_for_update()
        )
        if order is None or order.status == WorkStatus.completed:
            raise HTTPException(409, "The work order changed. Refresh the request and try again")

    start, end = order.scheduled_start, order.scheduled_end
    if data.schedule is not None:
        start, end = planned_slot(request, data.schedule)

    lead_id = team.technician_id if team is not None else order.technician_id
    assistant_ids = (
        team.assistant_ids if team is not None else [member.id for member in order.assistants]
    )
    if team is not None or (data.schedule is not None and start is not None):
        technicians = lock_eligible_team(request.branch_id, lead_id, assistant_ids, db)
        if start is not None:
            ensure_schedule_available(db, order, set(technicians), start, end)
        if team is not None:
            if team.previous_technician_id != order.technician_id:
                raise HTTPException(
                    409, "The assignment changed. Refresh the request and try again"
                )
            if lead_id != order.technician_id:
                if not team.reason:
                    raise HTTPException(422, "Enter a reason for changing the lead technician")
                record_reassignment(order, order.lead, technicians[lead_id], team.reason, user, db)
                order.lead = technicians[lead_id]
            record_team(order, [technicians[member_id] for member_id in assistant_ids], user, db)
    if data.schedule is not None:
        record_schedule(order, start, end, user, db)
    if data.price is not None:
        record_price(request, order, data.price, user, db)
