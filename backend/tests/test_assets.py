import uuid

from sqlalchemy import select

from app.models import Asset, Branch, BranchAccess, Role, ServiceRequest, User, WorkOrder
from app.security import issue_token


def test_asset_registry_access_edit_and_history(client, db, account):
    headers = {"Authorization": f"Bearer {issue_token(account)}"}
    branch = db.scalar(select(BranchAccess.branch_id).where(BranchAccess.user_id == account.id))
    outside = db.scalar(select(Branch.id).where(Branch.id != branch))
    data = {
        "branch_id": str(branch),
        "name": "Office AC",
        "asset_tag": "AC-001",
        "condition": "Operational",
        "location": "Second floor",
    }
    created = client.post("/api/assets", headers=headers, json=data)
    assert created.status_code == 201
    asset_id = created.json()["id"]
    assert client.post("/api/assets", headers=headers, json=data).status_code == 409
    assert (
        client.post(
            "/api/assets", headers=headers, json=data | {"branch_id": str(outside)}
        ).status_code
        == 403
    )
    asset = db.get(Asset, uuid.UUID(asset_id))
    report = ServiceRequest(
        branch_id=branch,
        asset_id=asset.id,
        submitted_by=account.id,
        title="Leaking",
        description="Water leaking",
        location="Office",
    )
    db.add(report)
    db.flush()
    db.add(
        WorkOrder(
            request_id=report.id,
            technician_id=account.id,
            assigned_by=account.id,
            labor_cost=10,
            materials_cost=5,
        )
    )
    hidden = Asset(branch_id=outside, name="Other", asset_tag="HIDDEN", condition="Working")
    manager = User(
        email="manager-assets@example.com",
        full_name="Manager",
        role=Role.branch_manager,
        password_hash=account.password_hash,
    )
    db.add_all([hidden, manager])
    db.commit()
    detail = client.get(f"/api/assets/{asset_id}", headers=headers).json()
    assert detail["total_cost"] == "15.00"
    assert detail["history"][0]["id"] == str(report.id)
    assert client.get(f"/api/assets/{hidden.id}", headers=headers).status_code == 404
    assert (
        client.get(
            "/api/assets", headers={"Authorization": f"Bearer {issue_token(manager)}"}
        ).status_code
        == 403
    )
    fields = {key: value for key, value in data.items() if key != "branch_id"} | {
        "condition": "Under repair"
    }
    assert (
        client.patch(f"/api/assets/{asset_id}", headers=headers, json=fields).json()["condition"]
        == "Under repair"
    )
    assert len(client.get("/api/assets?search=AC-001", headers=headers).json()) == 1
    db.delete(db.get(BranchAccess, (account.id, branch)))
    db.commit()
    assert client.get(f"/api/assets/{asset_id}", headers=headers).status_code == 404
