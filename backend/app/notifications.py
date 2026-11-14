import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import String, cast, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import NotificationRead, RequestEvent, Role, ServiceRequest, User, WorkOrder
from app.requests import visible
from app.security import current_user

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])

EVENTS = {
    Role.administrator: ("submitted", "work_completed"),
    Role.branch_manager: (
        "priority_changed",
        "work_started",
        "maintenance_logged",
        "work_completed",
        "work_returned",
        "verified_and_closed",
    ),
    Role.technician: ("work_order_assigned", "work_reassigned", "work_returned"),
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
            RequestEvent.actor_id != user.id,
        )
    )
    if user.role == Role.technician:
        query = query.where(
            RequestEvent.details["technician_id"].as_string() == str(user.id),
            select(WorkOrder.id)
            .where(
                WorkOrder.request_id == RequestEvent.request_id,
                WorkOrder.technician_id == user.id,
                func.replace(RequestEvent.details["work_order_id"].as_string(), "-", "")
                == func.replace(cast(WorkOrder.id, String), "-", ""),
            )
            .exists(),
        )
    return query


@router.get("")
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = inbox(user, db)
    unread = db.scalar(
        select(func.count()).select_from(
            query.where(NotificationRead.event_id.is_(None)).subquery()
        )
    )
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
                "created_at": event.created_at,
                "read": read_id is not None,
            }
            for event, title, read_id in rows
        ],
    }


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
