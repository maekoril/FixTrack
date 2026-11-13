import uuid

import pytest
from sqlalchemy import select

from app.models import (
    Asset,
    Branch,
    BranchAccess,
    RequestEvent,
    Role,
    ServiceRequest,
    User,
)
from app.security import issue_token


def auth(user):
    return {"Authorization": f"Bearer {issue_token(user)}"}


@pytest.fixture
def people(db, account):
    branch = db.scalar(select(Branch).where(Branch.name == "Branch A"))
    outside = db.scalar(select(Branch).where(Branch.name == "Branch B"))
    users = []
    for name, role, branch_id in [
        ("employee", Role.employee, branch.id),
        ("colleague", Role.employee, branch.id),
        ("outsider", Role.employee, outside.id),
        ("technician", Role.technician, branch.id),
    ]:
        user = User(
            email=f"{name}@example.com",
            full_name=name,
            role=role,
            password_hash=account.password_hash,
        )
        db.add(user)
        db.flush()
        db.add(BranchAccess(user_id=user.id, branch_id=branch_id))
        users.append(user)
    db.commit()
    return branch, outside, *users


def report(branch_id, **overrides):
    return {
        "branch_id": str(branch_id),
        "title": "Leaking air conditioner",
        "description": "Water is dripping onto the meeting room floor.",
        "location": "Meeting room",
        **overrides,
    }


def test_submission_detail_history_and_priority(client, db, account, people):
    branch, _, employee, *_ = people
    response = client.post("/api/requests", headers=auth(employee), json=report(branch.id))
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "submitted" and data["priority"] is None
    assert data["asset_id"] is None
    request_id = data["id"]
    detail = client.get(f"/api/requests/{request_id}", headers=auth(employee)).json()
    assert detail["events"][0]["action"] == "submitted"
    assert detail["submitted_by_name"] == employee.full_name
    response = client.patch(
        f"/api/requests/{request_id}/priority", headers=auth(account), json={"priority": "urgent"}
    )
    assert response.status_code == 200 and response.json()["priority"] == "urgent"
    # Repeating an identical priority is idempotent and does not duplicate history.
    client.patch(
        f"/api/requests/{request_id}/priority", headers=auth(account), json={"priority": "urgent"}
    )
    events = client.get(f"/api/requests/{request_id}", headers=auth(employee)).json()["events"]
    assert len(events) == 2
    priority_event = next(event for event in events if event["action"] == "priority_changed")
    assert priority_event["actor_name"] == account.full_name
    assert priority_event["details"] == {"from": None, "to": "urgent"}


def test_ownership_and_branch_isolation(client, account, people):
    branch, outside, employee, colleague, outsider, technician = people
    own = client.post("/api/requests", headers=auth(employee), json=report(branch.id)).json()
    foreign = client.post("/api/requests", headers=auth(outsider), json=report(outside.id)).json()
    for viewer in [colleague, outsider, technician]:
        assert client.get("/api/requests", headers=auth(viewer)).json() == (
            [foreign] if viewer.id == outsider.id else []
        )
        assert client.get(f"/api/requests/{own['id']}", headers=auth(viewer)).status_code == 404
        assert (
            client.patch(
                f"/api/requests/{own['id']}/priority",
                headers=auth(viewer),
                json={"priority": "high"},
            ).status_code
            == 403
        )
    assert client.get(f"/api/requests/{foreign['id']}", headers=auth(account)).status_code == 404
    assert (
        client.patch(
            f"/api/requests/{foreign['id']}/priority",
            headers=auth(account),
            json={"priority": "high"},
        ).status_code
        == 404
    )
    assert len(client.get("/api/requests", headers=auth(account)).json()) == 1
    assert (
        client.post("/api/requests", headers=auth(employee), json=report(outside.id)).status_code
        == 403
    )
    assert client.get(f"/api/requests?branch_id={outside.id}", headers=auth(account)).json() == []


def test_validation_and_role_rules(client, account, people):
    branch, _, employee, _, _, technician = people
    for user in [account, technician]:
        assert (
            client.post("/api/requests", headers=auth(user), json=report(branch.id)).status_code
            == 403
        )
    for changes in [{"title": "  "}, {"description": "short"}, {"location": " "}]:
        assert (
            client.post(
                "/api/requests", headers=auth(employee), json=report(branch.id, **changes)
            ).status_code
            == 422
        )
    assert client.post("/api/requests", json=report(branch.id)).status_code == 401
    assert client.get(f"/api/requests/{uuid.uuid4()}", headers=auth(employee)).status_code == 404


def test_initial_work_order_assignment(client, db, account, people):
    branch, outside, employee, _, outsider, technician = people
    outside_tech = User(
        email="outside-tech@example.com",
        full_name="Outside technician",
        role=Role.technician,
        password_hash=account.password_hash,
    )
    db.add(outside_tech)
    db.flush()
    db.add(BranchAccess(user_id=outside_tech.id, branch_id=outside.id))
    db.commit()

    own = client.post("/api/requests", headers=auth(employee), json=report(branch.id)).json()
    foreign = client.post("/api/requests", headers=auth(outsider), json=report(outside.id)).json()
    path = f"/api/requests/{own['id']}"
    assignment = f"{path}/work-orders"
    admin = auth(account)
    payload = {"technician_id": str(technician.id)}
    assert client.get(path, headers=admin).json()["eligible_technicians"] == [
        {"id": str(technician.id), "full_name": technician.full_name}
    ]
    assert client.get(path, headers=auth(employee)).json()["eligible_technicians"] is None
    assert client.post(assignment, headers=auth(employee), json=payload).status_code == 403
    assert (
        client.post(
            f"/api/requests/{foreign['id']}/work-orders", headers=admin, json=payload
        ).status_code
        == 404
    )
    for ineligible in (employee, outside_tech):
        assert (
            client.post(
                assignment, headers=admin, json={"technician_id": str(ineligible.id)}
            ).status_code
            == 422
        )
    technician.is_active = False
    db.commit()
    assert client.get(path, headers=admin).json()["eligible_technicians"] == []
    assert client.post(assignment, headers=admin, json=payload).status_code == 422
    technician.is_active = True
    db.commit()

    response = client.post(assignment, headers=admin, json=payload)
    assert response.status_code == 201
    order = response.json()
    assert order["technician_id"] == str(technician.id) and order["status"] == "assigned"
    assert client.post(assignment, headers=admin, json=payload).status_code == 409
    assert client.get("/api/requests", headers=auth(technician)).json() == [own]
    assert client.get(path, headers=auth(outside_tech)).status_code == 404
    detail = client.get(path, headers=admin).json()
    assert detail["eligible_technicians"] is None
    assert detail["status"] == "submitted"
    assigned = [event for event in detail["events"] if event["action"] == "work_order_assigned"]
    assert len(assigned) == 1
    assert assigned[0]["actor_name"] == account.full_name
    assert assigned[0]["details"] == {
        "work_order_id": order["id"],
        "technician_name": technician.full_name,
    }

    technician_auth = auth(technician)
    assert client.get(path, headers=technician_auth).json()["work_orders"] == [order]
    start = f"{assignment}/{order['id']}/start"
    assert client.post(start, headers=admin).status_code == 403
    assert client.post(start, headers=auth(outside_tech)).status_code == 404
    assert (
        client.post(f"{assignment}/{uuid.uuid4()}/start", headers=technician_auth).status_code
        == 404
    )

    grant = db.get(BranchAccess, (technician.id, branch.id))
    db.delete(grant)
    db.commit()
    assert client.post(start, headers=technician_auth).status_code == 404
    db.add(BranchAccess(user_id=technician.id, branch_id=branch.id))
    db.commit()

    for _ in range(2):
        started = client.post(start, headers=technician_auth)
        assert started.status_code == 200
        assert started.json() == order | {"status": "in_progress"}
    detail = client.get(path, headers=auth(employee)).json()
    assert detail["status"] == "in_progress"
    events = [event for event in detail["events"] if event["action"] == "work_started"]
    assert len(events) == 1
    assert events[0]["actor_name"] == technician.full_name
    assert events[0]["details"] == {"work_order_id": order["id"]}


def test_asset_scope_and_optional_link(client, db, people):
    branch, outside, employee, *_ = people
    asset = Asset(branch_id=branch.id, asset_tag="AC-1", name="AC", condition="broken")
    foreign = Asset(branch_id=outside.id, asset_tag="AC-2", name="AC", condition="broken")
    db.add_all([asset, foreign])
    db.commit()
    assert (
        client.post(
            "/api/requests", headers=auth(employee), json=report(branch.id, asset_id=str(asset.id))
        ).status_code
        == 201
    )
    for asset_id in [foreign.id, uuid.uuid4()]:
        assert (
            client.post(
                "/api/requests",
                headers=auth(employee),
                json=report(branch.id, asset_id=str(asset_id)),
            ).status_code
            == 422
        )
    listed = client.get(f"/api/requests/assets?branch_id={branch.id}", headers=auth(employee))
    assert [item["id"] for item in listed.json()] == [str(asset.id)]
    assert (
        client.get(
            f"/api/requests/assets?branch_id={outside.id}", headers=auth(employee)
        ).status_code
        == 403
    )


def test_filters_and_pagination(client, account, people):
    branch, _, employee, *_ = people
    first = client.post(
        "/api/requests", headers=auth(employee), json=report(branch.id, title="First issue")
    ).json()
    client.post(
        "/api/requests", headers=auth(employee), json=report(branch.id, title="Second issue")
    )
    client.patch(
        f"/api/requests/{first['id']}/priority", headers=auth(account), json={"priority": "high"}
    )
    assert len(client.get("/api/requests?priority=high", headers=auth(account)).json()) == 1
    assert len(client.get("/api/requests?status=closed", headers=auth(account)).json()) == 0
    assert (
        client.get("/api/requests?search=second", headers=auth(employee)).json()[0]["title"]
        == "Second issue"
    )
    page1 = client.get("/api/requests?limit=1", headers=auth(employee)).json()
    page2 = client.get("/api/requests?limit=1&offset=1", headers=auth(employee)).json()
    assert page1[0]["id"] != page2[0]["id"]
    assert client.get("/api/requests?limit=101", headers=auth(employee)).status_code == 422


def test_closed_request_and_revoked_branch_access(client, db, account, people):
    branch, _, employee, *_ = people
    result = client.post("/api/requests", headers=auth(employee), json=report(branch.id)).json()
    request = db.get(ServiceRequest, uuid.UUID(result["id"]))
    request.status = "closed"
    db.commit()
    assert (
        client.patch(
            f"/api/requests/{result['id']}/priority",
            headers=auth(account),
            json={"priority": "low"},
        ).status_code
        == 409
    )
    grant = db.get(BranchAccess, (employee.id, branch.id))
    db.delete(grant)
    db.commit()
    assert client.get(f"/api/requests/{result['id']}", headers=auth(employee)).status_code == 404
    assert len(db.scalars(select(RequestEvent)).all()) == 1
