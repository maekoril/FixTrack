import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import administrator, branch_ids
from app.db import get_db
from app.models import (
    Asset,
    Branch,
    Priority,
    RequestEvent,
    RequestStatus,
    Role,
    ServiceRequest,
    User,
    WorkOrder,
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


class DetailOutput(RequestOutput):
    events: list[EventOutput]


class PriorityInput(BaseModel):
    priority: Priority


def visible(user: User, db: Session):
    query = select(ServiceRequest).where(ServiceRequest.branch_id.in_(branch_ids(db, user.id)))
    if user.role == Role.employee:
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


@router.post("", response_model=RequestOutput, status_code=201)
def submit(data: RequestInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != Role.employee:
        raise HTTPException(403, "Only employees can submit service requests")
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
    return output(request, db) | {
        "events": [
            EventOutput(
                id=event.id,
                action=event.action,
                actor_name=name,
                created_at=event.created_at,
                details=event.details,
            )
            for event, name in events
        ]
    }


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
