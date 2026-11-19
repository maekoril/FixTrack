import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, case, cast, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    NotificationRead,
    RequestEvent,
    RequestStatus,
    Role,
    ServiceRequest,
    User,
    WorkOrder,
)
from app.requests import assigned_to, visible
from app.security import current_user

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])

EVENTS = {
    Role.administrator: ("submitted", "work_completed", "safety_flagged", "intake_confirmed"),
    Role.branch_manager: (
        "safety_flagged",
        "intake_confirmed",
        "priority_changed",
        "work_started",
        "maintenance_logged",
        "work_completed",
        "work_returned",
        "verified_and_closed",
        "work_schedule_changed",
    ),
    Role.technician: (
        "work_order_assigned",
        "work_reassigned",
        "work_returned",
        "work_team_changed",
        "work_schedule_changed",
    ),
}


def inbox(user: User, db: Session):
    query = (
        select(RequestEvent, ServiceRequest.title, NotificationRead.event_id.label("read_id"))
        .join(ServiceRequest, ServiceRequest.id == RequestEvent.request_id)
        .outerjoin(
            NotificationRead,
            (NotificationRead.event_id == RequestEvent.id) & (NotificationRead.user_id == user.id),
        )
        .where(
            RequestEvent.request_id.in_(visible(user, db).with_only_columns(ServiceRequest.id)),
            RequestEvent.action.in_(EVENTS[user.role]),
            or_(RequestEvent.actor_id != user.id, RequestEvent.action == "safety_flagged"),
        )
    )
    if user.role == Role.technician:
        query = query.where(
            select(WorkOrder.id)
            .where(
                WorkOrder.request_id == RequestEvent.request_id,
                assigned_to(user.id),
                or_(
                    RequestEvent.details["technician_id"].as_string() == str(user.id),
                    WorkOrder.technician_id != user.id,
                    RequestEvent.action.in_(("work_team_changed", "work_schedule_changed")),
                ),
                func.replace(RequestEvent.details["work_order_id"].as_string(), "-", "")
                == func.replace(cast(WorkOrder.id, String), "-", ""),
            )
            .exists(),
        )
    return query


@router.get("")
def list_notifications(
    category: Literal["approval", "update", "completed"] | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    query = inbox(user, db)
    unread = db.scalar(
        select(func.count()).select_from(
            query.where(NotificationRead.event_id.is_(None)).subquery()
        )
    )
    completed = RequestEvent.action.in_(("work_completed", "verified_and_closed"))
    notification_category = case((completed, "completed"), else_="update")
    if user.role == Role.administrator:
        latest_order = (
            select(WorkOrder.id)
            .where(WorkOrder.request_id == ServiceRequest.id)
            .order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
            .limit(1)
            .correlate(ServiceRequest)
            .scalar_subquery()
        )
        awaiting_review = (
            (RequestEvent.action == "work_completed")
            & (ServiceRequest.status == RequestStatus.awaiting_verification)
            & (
                func.replace(RequestEvent.details["work_order_id"].as_string(), "-", "")
                == func.replace(cast(latest_order, String), "-", "")
            )
        )
        notification_category = case(
            (awaiting_review, "approval"), (completed, "completed"), else_="update"
        )

    query = query.add_columns(notification_category.label("category"))
    if category is not None:
        query = query.where(notification_category == category)
    rows = db.execute(
        query.order_by(
            NotificationRead.event_id.is_not(None),
            RequestEvent.created_at.desc(),
            RequestEvent.id.desc(),
        ).limit(50)
    )
    return {
        "unread": unread,
        "items": [
            {
                "id": event.id,
                "request_id": event.request_id,
                "title": title,
                "action": event.action,
                "category": item_category,
                "created_at": event.created_at,
                "read": read_id is not None,
            }
            for event, title, read_id, item_category in rows
        ],
    }


@router.put("/read", status_code=204)
def mark_all_read(user: User = Depends(current_user), db: Session = Depends(get_db)):
    reads = NotificationRead.__table__
    unread = (
        inbox(user, db)
        .where(NotificationRead.event_id.is_(None))
        .with_only_columns(literal(user.id, type_=reads.c.user_id.type), RequestEvent.id)
        .order_by(RequestEvent.id)
    )
    insert = postgres_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(
        insert(reads)
        .from_select(["user_id", "event_id"], unread)
        .on_conflict_do_nothing(index_elements=[reads.c.user_id, reads.c.event_id])
    )
    db.commit()


@router.put("/{event_id}/read", status_code=204)
def mark_read(
    event_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = db.execute(inbox(user, db).where(RequestEvent.id == event_id)).first()
    if row is None:
        raise HTTPException(404, "Notification not found")
    if row.read_id is None:
        db.add(NotificationRead(user_id=user.id, event_id=event_id))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            if db.get(NotificationRead, (user.id, event_id)) is None:
                raise
