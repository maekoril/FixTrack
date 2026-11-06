from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Asset, Branch, ServiceRequest, WorkOrder


def test_asset_cannot_be_linked_to_request_in_another_branch(db, account):
    branches = db.query(Branch).order_by(Branch.name).all()
    asset = Asset(
        branch_id=branches[0].id,
        asset_tag="AC-001",
        name="Air conditioner",
        condition="operational",
    )
    db.add(asset)
    db.flush()
    db.add(
        ServiceRequest(
            branch_id=branches[1].id,
            submitted_by=account.id,
            asset_id=asset.id,
            title="Broken AC",
            description="No cooling",
            location="Office",
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_facility_request_without_asset_and_nonnegative_costs(db, account):
    branch = db.query(Branch).first()
    request = ServiceRequest(
        branch_id=branch.id,
        submitted_by=account.id,
        title="Leaking roof",
        description="Water in hallway",
        location="Hallway",
    )
    db.add(request)
    db.flush()
    assert request.asset_id is None
    db.add(
        WorkOrder(
            request_id=request.id,
            technician_id=account.id,
            assigned_by=account.id,
            labor_cost=Decimal("-1"),
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
