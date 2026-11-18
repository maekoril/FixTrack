import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.admin import administrator, branch_ids, commit
from app.db import get_db
from app.models import Asset, Branch, ServiceRequest, User, WorkOrder

router = APIRouter(prefix="/api/assets", tags=["Assets"])


class AssetFields(BaseModel):
    asset_tag: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]
    location: Annotated[str, StringConstraints(strip_whitespace=True, max_length=255)] = ""
    condition: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class AssetInput(AssetFields):
    branch_id: uuid.UUID


def scoped(db, user):
    return select(Asset).where(Asset.branch_id.in_(branch_ids(db, user.id)))


def output(asset, db):
    return {
        "id": asset.id,
        "branch_id": asset.branch_id,
        "branch_name": db.get(Branch, asset.branch_id).name,
        **{field: getattr(asset, field) for field in AssetFields.model_fields},
    }


@router.get("")
def list_assets(
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
    branch_id: uuid.UUID | None = None,
    search: str = Query("", max_length=150),
    offset: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
):
    query = scoped(db, user)
    if branch_id:
        query = query.where(Asset.branch_id == branch_id)
    if search.strip():
        query = query.where(
            or_(
                Asset.name.icontains(search.strip(), autoescape=True),
                Asset.asset_tag.icontains(search.strip(), autoescape=True),
            )
        )
    return [
        output(asset, db)
        for asset in db.scalars(
            query.order_by(Asset.asset_tag, Asset.id).offset(offset).limit(limit)
        )
    ]


@router.post("", status_code=201)
def create_asset(
    data: AssetInput, user: User = Depends(administrator), db: Session = Depends(get_db)
):
    if data.branch_id not in branch_ids(db, user.id):
        raise HTTPException(403, "Select a branch within your access")
    asset = Asset(**data.model_dump())
    db.add(asset)
    commit_asset(db)
    return output(asset, db)


def commit_asset(db):
    try:
        commit(db)
    except HTTPException as exc:
        if exc.status_code == 409:
            raise HTTPException(409, "That asset tag is already in use") from exc
        raise


def find_asset(asset_id, db, user, lock=False):
    query = scoped(db, user).where(Asset.id == asset_id)
    asset = db.scalar(query.with_for_update() if lock else query)
    if asset is None:
        raise HTTPException(404, "Asset not found")
    return asset


@router.patch("/{asset_id}")
def update_asset(
    asset_id: uuid.UUID,
    data: AssetFields,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    asset = find_asset(asset_id, db, user, lock=True)
    for field, value in data.model_dump().items():
        setattr(asset, field, value)
    commit_asset(db)
    return output(asset, db)


@router.get("/{asset_id}")
def detail(
    asset_id: uuid.UUID,
    user: User = Depends(administrator),
    db: Session = Depends(get_db),
    offset: int = Query(0, ge=0),
):
    asset = find_asset(asset_id, db, user)
    requests = db.scalars(
        select(ServiceRequest)
        .where(ServiceRequest.asset_id == asset.id)
        .order_by(ServiceRequest.created_at.desc(), ServiceRequest.id.desc())
        .offset(offset)
        .limit(25)
    ).all()
    costs = db.scalar(
        select(func.coalesce(func.sum(WorkOrder.labor_cost + WorkOrder.materials_cost), 0))
        .join(ServiceRequest, ServiceRequest.id == WorkOrder.request_id)
        .where(ServiceRequest.asset_id == asset.id)
    )
    history = []
    for request in requests:
        orders = db.execute(
            select(WorkOrder, User.full_name)
            .join(User, User.id == WorkOrder.technician_id)
            .where(WorkOrder.request_id == request.id)
            .order_by(WorkOrder.created_at, WorkOrder.id)
        ).all()
        history.append(
            {
                "id": request.id,
                "title": request.title,
                "status": request.status,
                "created_at": request.created_at,
                "orders": [
                    {
                        "technician": name,
                        "status": order.status,
                        "cost": format(order.labor_cost + order.materials_cost, ".2f"),
                    }
                    for order, name in orders
                ],
            }
        )
    return output(asset, db) | {"total_cost": format(costs, ".2f"), "history": history}
