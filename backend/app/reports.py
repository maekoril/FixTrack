import uuid
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session

from app.admin import administrator
from app.db import get_db
from app.models import (
    Branch,
    BranchAccess,
    RequestEvent,
    RequestStatus,
    ServiceRequest,
    User,
    WorkOrder,
    WorkStatus,
)

router = APIRouter(prefix="/api/reports", tags=["Reports"])


class RepairTotals(BaseModel):
    closed_requests: int
    completed_orders: int
    labor_cost: Decimal
    materials_cost: Decimal
    total_cost: Decimal


class BranchRepairs(RepairTotals):
    branch_id: uuid.UUID
    branch_name: str


class RepairReport(BaseModel):
    totals: RepairTotals
    branches: list[BranchRepairs]


@router.get("/repairs", response_model=RepairReport)
def repair_report(
    start_date: date,
    end_date: date,
    branch_id: uuid.UUID | None = None,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    if end_date < start_date or end_date == date.max:
        raise HTTPException(422, "Enter a valid date range")
    start = datetime.combine(start_date, time.min, UTC)
    end = datetime.combine(end_date + timedelta(days=1), time.min, UTC)

    branches = (
        select(Branch.id, Branch.name).join(BranchAccess).where(BranchAccess.user_id == user.id)
    )
    if branch_id is not None:
        branches = branches.where(Branch.id == branch_id)
    scope = branches.cte()

    closures = (
        select(ServiceRequest.branch_id, func.count().label("closed_requests"))
        .join(scope, scope.c.id == ServiceRequest.branch_id)
        .where(
            ServiceRequest.status == RequestStatus.closed,
            ServiceRequest.closed_at >= start,
            ServiceRequest.closed_at < end,
        )
        .group_by(ServiceRequest.branch_id)
        .subquery()
    )

    # Completion events timestamp existing work orders. SQLite stores UUID columns without hyphens.
    completion = (
        select(RequestEvent.id)
        .where(
            RequestEvent.request_id == WorkOrder.request_id,
            RequestEvent.action == "work_completed",
            func.replace(RequestEvent.details["work_order_id"].as_string(), "-", "")
            == func.replace(cast(WorkOrder.id, String), "-", ""),
            RequestEvent.created_at >= start,
            RequestEvent.created_at < end,
        )
        .exists()
    )
    repairs = (
        select(
            ServiceRequest.branch_id,
            func.count().label("completed_orders"),
            func.sum(WorkOrder.labor_cost).label("labor_cost"),
            func.sum(WorkOrder.materials_cost).label("materials_cost"),
        )
        .select_from(WorkOrder)
        .join(ServiceRequest, ServiceRequest.id == WorkOrder.request_id)
        .join(scope, scope.c.id == ServiceRequest.branch_id)
        .where(WorkOrder.status == WorkStatus.completed, completion)
        .group_by(ServiceRequest.branch_id)
        .subquery()
    )

    rows = db.execute(
        select(
            scope.c.id,
            scope.c.name,
            closures.c.closed_requests,
            repairs.c.completed_orders,
            repairs.c.labor_cost,
            repairs.c.materials_cost,
        )
        .outerjoin(closures, closures.c.branch_id == scope.c.id)
        .outerjoin(repairs, repairs.c.branch_id == scope.c.id)
        .order_by(scope.c.name)
    )
    result = []
    zero = Decimal("0.00")
    for id_, name, closed, completed, labor, materials in rows:
        labor = labor if labor is not None else zero
        materials = materials if materials is not None else zero
        result.append(
            BranchRepairs(
                branch_id=id_,
                branch_name=name,
                closed_requests=closed or 0,
                completed_orders=completed or 0,
                labor_cost=labor,
                materials_cost=materials,
                total_cost=labor + materials,
            )
        )
    if branch_id is not None and not result:
        raise HTTPException(404, "Branch not found")
    return RepairReport(
        branches=result,
        totals=RepairTotals(
            closed_requests=sum(row.closed_requests for row in result),
            completed_orders=sum(row.completed_orders for row in result),
            labor_cost=sum((row.labor_cost for row in result), zero),
            materials_cost=sum((row.materials_cost for row in result), zero),
            total_cost=sum((row.total_cost for row in result), zero),
        ),
    )
