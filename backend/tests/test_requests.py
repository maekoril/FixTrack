import uuid
from io import BytesIO

import pytest
from PIL import Image
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
        ("branch_manager", Role.branch_manager, branch.id),
        ("colleague", Role.branch_manager, branch.id),
        ("outsider", Role.branch_manager, outside.id),
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


def test_dashboard_counts_match_branch_scoped_queues(client, account, people):
    branch, outside, manager, _, outsider, technician = people
    admin = auth(account)
    dashboard = "/api/requests/dashboard"

    def submit(reporter, branch_id):
        return client.post("/api/requests", headers=auth(reporter), json=report(branch_id)).json()

    def assign(request):
        return client.post(
            f"/api/requests/{request['id']}/work-orders",
            headers=admin,
            json={"technician_id": str(technician.id)},
        ).json()

    waiting = submit(manager, branch.id)
    assigned = submit(manager, branch.id)
    assign(assigned)
    active = submit(manager, branch.id)
    completed = submit(manager, branch.id)
    for request in (active, completed):
        order = assign(request)
        path = f"/api/requests/{request['id']}/work-orders/{order['id']}"
        assert client.post(f"{path}/start", headers=auth(technician)).status_code == 200
    assert (
        client.post(
            f"{path}/complete",
            headers=auth(technician),
            json={"labor_cost": "0", "materials_cost": "0"},
        ).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/requests/{active['id']}/priority", headers=admin, json={"priority": "urgent"}
        ).status_code
        == 200
    )
    closed = submit(manager, branch.id)
    order = assign(closed)
    closed_path = f"/api/requests/{closed['id']}"
    work = f"{closed_path}/work-orders/{order['id']}"
    assert (
        client.patch(
            f"{closed_path}/priority", headers=admin, json={"priority": "urgent"}
        ).status_code
        == 200
    )
    assert client.post(f"{work}/start", headers=auth(technician)).status_code == 200
    assert (
        client.post(
            f"{work}/complete",
            headers=auth(technician),
            json={"labor_cost": "0", "materials_cost": "0"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{closed_path}/verify", headers=admin, json={"work_order_id": order["id"]}
        ).status_code
        == 200
    )
    submit(outsider, outside.id)
    expected = {
        "needs_assignment": waiting,
        "urgent_open": active,
        "work_in_progress": active,
        "awaiting_verification": completed,
    }
    assert client.get(dashboard, headers=auth(manager)).status_code == 403
    assert client.get(dashboard, headers=admin).json() == dict.fromkeys(expected, 1)
    assert client.get(dashboard, headers=admin, params={"branch_id": outside.id}).json() == (
        dict.fromkeys(expected, 0)
    )
    for focus, request in expected.items():
        result = client.get(
            "/api/requests", headers=admin, params={"focus": focus, "branch_id": branch.id}
        )
        assert [item["id"] for item in result.json()] == [request["id"]]


def test_private_issue_and_repair_photos(client, db, account, people):
    branch, _, manager, colleague, _, technician = people
    source = BytesIO()
    Image.new("RGB", (640, 480), "blue").save(source, "PNG")
    admin, reporter, tech = auth(account), auth(manager), auth(technician)
    created = client.post("/api/requests", headers=reporter, json=report(branch.id)).json()
    path = f"/api/requests/{created['id']}"
    photos = f"{path}/photos"
    assert (
        client.post(
            photos, headers=reporter, params={"name": "fake.png"}, content=b"invalid"
        ).status_code
        == 422
    )
    assert (
        client.post(
            photos,
            headers=reporter,
            params={"name": "large.png"},
            content=b"x" * (8 * 1024 * 1024 + 1),
        ).status_code
        == 413
    )
    added = client.post(
        photos, headers=reporter, params={"name": "leak.png"}, content=source.getvalue()
    )
    assert added.status_code == 201
    photo_id = added.json()["id"]
    photo_url = f"{photos}/{photo_id}"
    assert client.get(photo_url, headers=auth(colleague)).status_code == 404
    assert client.get(photo_url, headers=tech).status_code == 404
    assert client.get(photo_url).status_code == 401
    preview = client.get(photo_url, headers=admin, params={"thumbnail": True})
    assert preview.headers["cache-control"] == "private, no-store"
    assert Image.open(BytesIO(preview.content)).size == (360, 270)
    assert Image.open(BytesIO(client.get(photo_url, headers=admin).content)).size == (640, 480)
    order = client.post(
        f"{path}/work-orders", headers=admin, json={"technician_id": str(technician.id)}
    ).json()
    order_path = f"{path}/work-orders/{order['id']}"
    params = {"name": "repaired.png", "work_order_id": order["id"]}
    assert (
        client.post(photos, headers=tech, params=params, content=source.getvalue()).status_code
        == 409
    )
    assert client.post(f"{order_path}/start", headers=tech).status_code == 200
    assert client.get(photo_url, headers=tech).status_code == 200
    repair = client.post(photos, headers=tech, params=params, content=source.getvalue())
    assert repair.status_code == 201
    metadata = client.get(path, headers=reporter).json()["photos"]
    assert {photo["id"]: photo["work_order_id"] for photo in metadata} == {
        photo_id: None,
        repair.json()["id"]: order["id"],
    }
    db.delete(db.get(BranchAccess, (technician.id, branch.id)))
    db.commit()
    assert client.get(photo_url, headers=tech).status_code == 404


def test_submission_detail_history_and_priority(client, db, account, people):
    branch, _, branch_manager, *_ = people
    response = client.post("/api/requests", headers=auth(branch_manager), json=report(branch.id))
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "submitted" and data["priority"] is None
    assert data["asset_id"] is None
    request_id = data["id"]
    detail = client.get(f"/api/requests/{request_id}", headers=auth(branch_manager)).json()
    assert detail["events"][0]["action"] == "submitted"
    assert detail["submitted_by_name"] == branch_manager.full_name
    response = client.patch(
        f"/api/requests/{request_id}/priority", headers=auth(account), json={"priority": "urgent"}
    )
    assert response.status_code == 200 and response.json()["priority"] == "urgent"
    # Repeating an identical priority is idempotent and does not duplicate history.
    client.patch(
        f"/api/requests/{request_id}/priority", headers=auth(account), json={"priority": "urgent"}
    )
    events = client.get(f"/api/requests/{request_id}", headers=auth(branch_manager)).json()[
        "events"
    ]
    assert len(events) == 2
    priority_event = next(event for event in events if event["action"] == "priority_changed")
    assert priority_event["actor_name"] == account.full_name
    assert priority_event["details"] == {"from": None, "to": "urgent"}


def test_ownership_and_branch_isolation(client, account, db, people):
    branch, outside, branch_manager, colleague, outsider, technician = people
    own = client.post("/api/requests", headers=auth(branch_manager), json=report(branch.id)).json()
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
        client.post(
            "/api/requests", headers=auth(branch_manager), json=report(outside.id)
        ).status_code
        == 403
    )
    assert client.get(f"/api/requests?branch_id={outside.id}", headers=auth(account)).json() == []
    db.add(BranchAccess(user_id=branch_manager.id, branch_id=outside.id))
    db.commit()
    second_branch_report = client.post(
        "/api/requests", headers=auth(branch_manager), json=report(outside.id)
    )
    assert second_branch_report.status_code == 201
    assert client.get(
        f"/api/requests?branch_id={outside.id}", headers=auth(branch_manager)
    ).json() == [second_branch_report.json()]


def test_validation_and_role_rules(client, account, people):
    branch, _, branch_manager, _, _, technician = people
    for user in [account, technician]:
        assert (
            client.post("/api/requests", headers=auth(user), json=report(branch.id)).status_code
            == 403
        )
    for changes in [{"title": "  "}, {"description": "short"}, {"location": " "}]:
        assert (
            client.post(
                "/api/requests", headers=auth(branch_manager), json=report(branch.id, **changes)
            ).status_code
            == 422
        )
    assert client.post("/api/requests", json=report(branch.id)).status_code == 401
    assert (
        client.get(f"/api/requests/{uuid.uuid4()}", headers=auth(branch_manager)).status_code == 404
    )


def test_initial_work_order_assignment(client, db, account, people):
    branch, outside, branch_manager, _, outsider, technician = people
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

    own = client.post("/api/requests", headers=auth(branch_manager), json=report(branch.id)).json()
    foreign = client.post("/api/requests", headers=auth(outsider), json=report(outside.id)).json()
    path = f"/api/requests/{own['id']}"
    assignment = f"{path}/work-orders"
    admin = auth(account)
    payload = {"technician_id": str(technician.id)}
    assert client.get(path, headers=admin).json()["eligible_technicians"] == [
        {"id": str(technician.id), "full_name": technician.full_name}
    ]
    assert client.get(path, headers=auth(branch_manager)).json()["eligible_technicians"] is None
    assert client.post(assignment, headers=auth(branch_manager), json=payload).status_code == 403
    assert (
        client.post(
            f"/api/requests/{foreign['id']}/work-orders", headers=admin, json=payload
        ).status_code
        == 404
    )
    for ineligible in (branch_manager, outside_tech):
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
    assert detail["eligible_technicians"] == [
        {"id": str(technician.id), "full_name": technician.full_name}
    ]
    assert detail["status"] == "submitted"
    assigned = [event for event in detail["events"] if event["action"] == "work_order_assigned"]
    assert len(assigned) == 1
    assert assigned[0]["actor_name"] == account.full_name
    assert assigned[0]["details"] == {
        "work_order_id": order["id"],
        "technician_name": technician.full_name,
        "technician_id": str(technician.id),
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
    detail = client.get(path, headers=auth(branch_manager)).json()
    assert detail["status"] == "in_progress"
    events = [event for event in detail["events"] if event["action"] == "work_started"]
    assert len(events) == 1
    assert events[0]["actor_name"] == technician.full_name
    assert events[0]["details"] == {"work_order_id": order["id"]}


def test_technician_logs_and_completes_work(client, account, db, people):
    branch, _, manager, _, _, technician = people
    created = client.post("/api/requests", headers=auth(manager), json=report(branch.id)).json()
    path = f"/api/requests/{created['id']}"
    admin = auth(account)
    tech = auth(technician)
    manager_auth = auth(manager)
    inbox = "/api/notifications"
    submitted = client.get(inbox, headers=admin).json()
    assert submitted["unread"] == 1
    assert submitted["items"][0]["action"] == "submitted"
    read = f"{inbox}/{submitted['items'][0]['id']}/read"
    assert client.put(read, headers=manager_auth).status_code == 404
    for _ in range(2):
        assert client.put(read, headers=admin).status_code == 204
    assert client.get(inbox, headers=admin).json()["unread"] == 0
    order = client.post(
        f"{path}/work-orders", headers=admin, json={"technician_id": str(technician.id)}
    ).json()
    assert client.get(inbox, headers=tech).json()["items"][0]["action"] == "work_order_assigned"
    work = f"{path}/work-orders/{order['id']}"
    entry = {"action": "Replaced valve", "notes": "Tested for leaks."}
    costs = {"labor_cost": "120.25", "materials_cost": "0"}
    assert client.post(f"{work}/logs", headers=tech, json=entry).status_code == 409
    assert client.post(f"{work}/complete", headers=tech, json=costs).status_code == 409
    assert client.post(f"{work}/start", headers=tech).status_code == 200
    assert client.post(f"{work}/logs", headers=admin, json=entry).status_code == 403
    log = client.post(f"{work}/logs", headers=tech, json=entry)
    assert log.status_code == 201
    assert log.json()["recorded_by_name"] == technician.full_name
    assert client.get(path, headers=tech).json()["maintenance_logs"] == [log.json()]

    db.delete(db.get(BranchAccess, (technician.id, branch.id)))
    db.commit()
    assert client.post(f"{work}/logs", headers=tech, json=entry).status_code == 404
    assert client.get(inbox, headers=tech).json()["items"] == []
    assert client.post(f"{work}/complete", headers=tech, json=costs).status_code == 404
    db.add(BranchAccess(user_id=technician.id, branch_id=branch.id))
    db.commit()
    for invalid_cost in ("-1", "1.001", "10000000000", "NaN"):
        assert (
            client.post(
                f"{work}/complete", headers=tech, json=costs | {"labor_cost": invalid_cost}
            ).status_code
            == 422
        )
    for _ in range(2):
        response = client.post(f"{work}/complete", headers=tech, json=costs)
        assert response.status_code == 200
        assert response.json()["status"] == "completed"
    assert client.post(f"{work}/logs", headers=tech, json=entry).status_code == 409
    detail = client.get(path, headers=admin).json()
    assert detail["work_orders"][0]["labor_cost"] == "120.25"
    assert detail["maintenance_logs"] == [log.json()]
    assert [event["action"] for event in detail["events"]].count("work_completed") == 1
    manager_detail = client.get(path, headers=auth(manager)).json()
    assert manager_detail["status"] == "awaiting_verification"
    assert manager_detail["work_orders"] == []
    assert manager_detail["maintenance_logs"] == [log.json()]
    assert client.get(inbox, headers=admin).json()["items"][0]["action"] == "work_completed"
    assert {item["action"] for item in client.get(inbox, headers=manager_auth).json()["items"]} == {
        "work_started",
        "maintenance_logged",
        "work_completed",
    }

    review = {"work_order_id": order["id"]}
    returned = review | {"technician_id": str(technician.id), "reason": "Retest under load"}
    assert client.post(f"{path}/verify", headers=tech, json=review).status_code == 403
    assert (
        client.post(
            f"{path}/return", headers=admin, json=returned | {"technician_id": str(manager.id)}
        ).status_code
        == 422
    )
    response = client.post(f"{path}/return", headers=admin, json=returned)
    assert response.status_code == 201
    follow_up = response.json()
    assert follow_up["id"] != order["id"]
    assert client.post(f"{path}/return", headers=admin, json=returned).status_code == 409
    assert client.post(f"{path}/verify", headers=admin, json=review).status_code == 409
    assert client.get(path, headers=auth(manager)).json()["status"] == "in_progress"
    follow_up_path = f"{path}/work-orders/{follow_up['id']}"
    assert client.post(f"{follow_up_path}/start", headers=tech).status_code == 200
    assert client.post(f"{follow_up_path}/complete", headers=tech, json=costs).status_code == 200
    assert client.post(f"{path}/verify", headers=admin, json=review).status_code == 409
    closed = client.post(
        f"{path}/verify",
        headers=admin,
        json={"work_order_id": follow_up["id"], "notes": "Passed under load"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    saved = db.get(ServiceRequest, uuid.UUID(created["id"]))
    assert saved.closed_by == account.id and saved.closed_at is not None
    detail = client.get(path, headers=admin).json()
    assert [item["id"] for item in detail["work_orders"]] == [order["id"], follow_up["id"]]
    assert detail["maintenance_logs"] == [log.json()]
    manager_events = client.get(path, headers=auth(manager)).json()["events"]
    assert any(event["details"].get("reason") == "Retest under load" for event in manager_events)
    assert any(event["details"].get("notes") == "Passed under load" for event in manager_events)


@pytest.mark.parametrize("started", [False, True])
def test_admin_reassigns_active_work(client, account, db, people, started):
    branch, outside, manager, _, _, technician = people
    replacement = User(
        email="replacement@example.com",
        full_name="Replacement Technician",
        role=Role.technician,
        password_hash=account.password_hash,
    )
    db.add(replacement)
    db.flush()
    db.add(BranchAccess(user_id=replacement.id, branch_id=outside.id))
    db.commit()
    admin = auth(account)
    created = client.post("/api/requests", headers=auth(manager), json=report(branch.id)).json()
    path = f"/api/requests/{created['id']}"
    order = client.post(
        f"{path}/work-orders", headers=admin, json={"technician_id": str(technician.id)}
    ).json()
    work = f"{path}/work-orders/{order['id']}"
    entry = {"action": "Diagnosis", "notes": "Found a damaged valve"}
    if started:
        assert client.post(f"{work}/start", headers=auth(technician)).status_code == 200
        assert client.post(f"{work}/logs", headers=auth(technician), json=entry).status_code == 201
    data = {
        "technician_id": str(replacement.id),
        "previous_technician_id": str(technician.id),
        "reason": "Technician unavailable",
    }
    assert client.post(f"{work}/reassign", headers=auth(manager), json=data).status_code == 403
    assert client.post(f"{work}/reassign", headers=admin, json=data).status_code == 422
    db.add(BranchAccess(user_id=replacement.id, branch_id=branch.id))
    db.delete(db.get(BranchAccess, (technician.id, branch.id)))
    db.commit()
    reassigned = client.post(f"{work}/reassign", headers=admin, json=data)
    assert reassigned.status_code == 200
    assert reassigned.json()["id"] == order["id"]
    assert reassigned.json()["status"] == ("in_progress" if started else "assigned")
    assert client.post(f"{work}/reassign", headers=admin, json=data).status_code == 409
    db.add(BranchAccess(user_id=technician.id, branch_id=branch.id))
    db.commit()
    assert client.get(path, headers=auth(technician)).status_code == 404
    assert client.get("/api/notifications", headers=auth(technician)).json()["items"] == []
    replacement_inbox = client.get("/api/notifications", headers=auth(replacement)).json()
    assert [item["action"] for item in replacement_inbox["items"]] == ["work_reassigned"]
    assert client.post(f"{work}/start", headers=auth(technician)).status_code == 404
    detail = client.get(path, headers=auth(replacement)).json()
    assert len(detail["maintenance_logs"]) == int(started)
    (event,) = [event for event in detail["events"] if event["action"] == "work_reassigned"]
    assert event["details"]["reason"] == data["reason"]
    assert event["details"]["previous_technician_id"] == str(technician.id)
    assert client.post(f"{work}/start", headers=auth(replacement)).status_code == 200
    costs = {"labor_cost": "10.00", "materials_cost": "0"}
    assert client.post(f"{work}/complete", headers=auth(replacement), json=costs).status_code == 200
    assert client.post(f"{work}/reassign", headers=admin, json=data).status_code == 409
    assert (
        client.post(
            f"{path}/verify", headers=admin, json={"work_order_id": order["id"]}
        ).status_code
        == 200
    )
    assert client.get(path, headers=auth(manager)).json()["status"] == "closed"


def test_asset_scope_and_optional_link(client, db, people):
    branch, outside, branch_manager, *_ = people
    asset = Asset(branch_id=branch.id, asset_tag="AC-1", name="AC", condition="broken")
    foreign = Asset(branch_id=outside.id, asset_tag="AC-2", name="AC", condition="broken")
    db.add_all([asset, foreign])
    db.commit()
    assert (
        client.post(
            "/api/requests",
            headers=auth(branch_manager),
            json=report(branch.id, asset_id=str(asset.id)),
        ).status_code
        == 201
    )
    for asset_id in [foreign.id, uuid.uuid4()]:
        assert (
            client.post(
                "/api/requests",
                headers=auth(branch_manager),
                json=report(branch.id, asset_id=str(asset_id)),
            ).status_code
            == 422
        )
    listed = client.get(f"/api/requests/assets?branch_id={branch.id}", headers=auth(branch_manager))
    assert [item["id"] for item in listed.json()] == [str(asset.id)]
    assert (
        client.get(
            f"/api/requests/assets?branch_id={outside.id}", headers=auth(branch_manager)
        ).status_code
        == 403
    )


def test_filters_and_pagination(client, account, people):
    branch, _, branch_manager, *_ = people
    first = client.post(
        "/api/requests", headers=auth(branch_manager), json=report(branch.id, title="First issue")
    ).json()
    client.post(
        "/api/requests", headers=auth(branch_manager), json=report(branch.id, title="Second issue")
    )
    client.patch(
        f"/api/requests/{first['id']}/priority", headers=auth(account), json={"priority": "high"}
    )
    assert len(client.get("/api/requests?priority=high", headers=auth(account)).json()) == 1
    assert len(client.get("/api/requests?status=closed", headers=auth(account)).json()) == 0
    assert (
        client.get("/api/requests?search=second", headers=auth(branch_manager)).json()[0]["title"]
        == "Second issue"
    )
    page1 = client.get("/api/requests?limit=1", headers=auth(branch_manager)).json()
    page2 = client.get("/api/requests?limit=1&offset=1", headers=auth(branch_manager)).json()
    assert page1[0]["id"] != page2[0]["id"]
    assert client.get("/api/requests?limit=101", headers=auth(branch_manager)).status_code == 422


def test_closed_request_and_revoked_branch_access(client, db, account, people):
    branch, _, branch_manager, *_ = people
    result = client.post(
        "/api/requests", headers=auth(branch_manager), json=report(branch.id)
    ).json()
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
    grant = db.get(BranchAccess, (branch_manager.id, branch.id))
    db.delete(grant)
    db.commit()
    assert (
        client.get(f"/api/requests/{result['id']}", headers=auth(branch_manager)).status_code == 404
    )
    assert len(db.scalars(select(RequestEvent)).all()) == 1
