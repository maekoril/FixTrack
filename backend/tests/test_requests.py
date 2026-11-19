import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import (
    Asset,
    Branch,
    BranchAccess,
    RequestEvent,
    RequestStatus,
    Role,
    ServiceCategory,
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


@pytest.fixture
def budget_order(client, account, people):
    branch, _, manager, _, _, technician = people
    request = client.post("/api/requests", headers=auth(manager), json=report(branch.id)).json()
    path = f"/api/requests/{request['id']}"
    result = client.patch(
        f"{path}/estimate",
        headers=auth(account),
        json={"difficulty": None, "duration_override_minutes": 120},
    )
    assert result.status_code == 200
    order = client.post(
        f"{path}/work-orders", headers=auth(account), json={"technician_id": str(technician.id)}
    ).json()
    return path, f"{path}/work-orders/{order['id']}", technician


def material_quote(**overrides):
    return {
        "hourly_rate": "250.00",
        "materials_items": [
            {"name": "Faucet", "quantity": "1", "unit_price": "450", "source": "Supplier quote A"},
            {"name": "Tape", "quantity": "2", "unit_price": "25", "source": "Price list Nov 19"},
        ],
        **overrides,
    }


def test_itemized_budget_approval_and_overrun_completion(client, db, account, people, budget_order):
    path, work, technician = budget_order
    admin, tech = auth(account), auth(technician)
    first = client.patch(f"{work}/price", headers=admin, json=material_quote())
    assert first.status_code == 200, first.text
    quote = first.json()["price_estimate"]
    assert quote["labor_estimate"] == "500.00"
    assert quote["materials_estimate"] == "500.00"
    assert quote["amount"] == "1000.00" and quote["version"] == 1
    assert quote["materials_items"][1]["total"] == "50.00"
    # Repeating the same draft must not manufacture a new version.
    repeated = client.patch(f"{work}/price", headers=admin, json=material_quote()).json()
    assert repeated["price_estimate"] == quote
    approval = {"version": 1}
    approved = client.post(f"{work}/price/approve", headers=admin, json=approval)
    assert approved.status_code == 200
    snapshot = approved.json()["approved_price"]
    assert snapshot["quote"] == quote
    assert snapshot["approved_by"] == str(account.id)
    assert snapshot["approved_by_name"] == account.full_name
    assert snapshot["approved_at"]
    retry = client.post(f"{work}/price/approve", headers=admin, json=approval)
    assert retry.json()["approved_price"] == snapshot

    # A newer draft cannot silently raise the approved spending baseline.
    revised = client.patch(
        f"{work}/price", headers=admin, json=material_quote(hourly_rate="500.00")
    ).json()
    assert revised["price_estimate"]["version"] == 2
    assert revised["approved_price"] == snapshot
    assert client.post(f"{work}/price/approve", headers=admin, json=approval).status_code == 409
    assert client.post(f"{work}/start", headers=tech).status_code == 200
    costs = {"labor_cost": "600.00", "materials_cost": "500.00"}
    for reason in ("", "   "):
        failed = client.post(
            f"{work}/complete", headers=tech, json=costs | {"overrun_reason": reason}
        )
        assert failed.status_code == 422
    detail = client.get(path, headers=admin).json()
    assert detail["status"] == "in_progress"
    assert detail["work_orders"][0]["labor_cost"] == "0.00"
    assert not any(event["action"] == "work_completed" for event in detail["events"])
    costs["overrun_reason"] = "Additional hour required to remove corroded fittings."
    for _ in range(2):
        finished = client.post(f"{work}/complete", headers=tech, json=costs)
        assert finished.status_code == 200, finished.text
        assert finished.json()["overrun_reason"] == costs["overrun_reason"]
        assert finished.json()["approved_price"] == snapshot
    assert (
        client.post(f"{work}/price/approve", headers=admin, json={"version": 2}).status_code == 409
    )
    detail = client.get(path, headers=admin).json()
    assert [event["action"] for event in detail["events"]].count("work_completed") == 1
    approvals = [event for event in detail["events"] if event["action"] == "work_price_approved"]
    assert len(approvals) == 1 and approvals[0]["details"]["approval"] == snapshot
    manager_detail = client.get(path, headers=auth(people[2])).json()
    assert manager_detail["work_orders"] == []
    assert not any(event["action"] == "work_price_approved" for event in manager_detail["events"])


@pytest.mark.parametrize(
    "change",
    [
        {"quantity": "0"},
        {"quantity": "-1"},
        {"quantity": "0.0001"},
        {"unit_price": "-1"},
        {"unit_price": "NaN"},
        {"unit_price": "1.001"},
        {"source": "  "},
        {"name": " "},
        {"quantity": "1000001"},
        {"quantity": "1000000", "unit_price": "9999999999.99"},
    ],
)
def test_invalid_budget_items_do_not_save(client, account, budget_order, change):
    path, work, _ = budget_order
    data = material_quote()
    data["materials_items"][0].update(change)
    result = client.patch(f"{work}/price", headers=auth(account), json=data)
    assert result.status_code == 422, result.text
    detail = client.get(path, headers=auth(account)).json()
    assert detail["work_orders"][0]["price_estimate"] is None
    assert not any(event["action"] == "work_price_changed" for event in detail["events"])


def test_budget_rounding_reapproval_and_access(client, db, account, people, budget_order):
    path, work, technician = budget_order
    admin = auth(account)
    assert (
        client.post(f"{work}/price/approve", headers=admin, json={"version": 0}).status_code == 409
    )
    data = material_quote(
        hourly_rate="0",
        materials_items=[
            {"name": "Cable", "quantity": "0.125", "unit_price": "1", "source": "Quote B"},
            {"name": "Hose", "quantity": "0.125", "unit_price": "1", "source": "Quote B"},
        ],
    )
    quote = client.patch(f"{work}/price", headers=admin, json=data).json()["price_estimate"]
    assert quote["amount"] == "0.26"  # Round individual lines, then sum.
    for user in (people[2], technician):
        assert (
            client.post(
                f"{work}/price/approve", headers=auth(user), json={"version": 1}
            ).status_code
            == 403
        )
    first = client.post(f"{work}/price/approve", headers=admin, json={"version": 1}).json()[
        "approved_price"
    ]
    zero = client.patch(
        f"{work}/price", headers=admin, json=material_quote(hourly_rate="0", materials_items=[])
    )
    assert zero.json()["price_estimate"]["amount"] == "0.00"
    second = client.post(f"{work}/price/approve", headers=admin, json={"version": 2})
    assert second.status_code == 200
    assert second.json()["approved_price"]["quote"]["amount"] == "0.00"
    history = client.get(path, headers=admin).json()["events"]
    approvals = [event for event in history if event["action"] == "work_price_approved"]
    assert len(approvals) == 2
    replacement = next(
        event for event in approvals if event["details"]["approval"]["quote"]["version"] == 2
    )
    assert replacement["details"]["previous_approval"] == first
    db.query(BranchAccess).filter(BranchAccess.user_id == account.id).delete()
    db.commit()
    assert (
        client.post(f"{work}/price/approve", headers=admin, json={"version": 2}).status_code == 404
    )


def test_legacy_estimates_and_completion_without_overrun(client, db, account, budget_order):
    from app.models import WorkOrder

    path, work, technician = budget_order
    admin, tech = auth(account), auth(technician)
    quote = client.patch(
        f"{work}/price", headers=admin, json={"hourly_rate": "250", "materials_estimate": "500"}
    ).json()["price_estimate"]
    # Simulate a saved pre-migration quote that has no version or itemization.
    legacy = {
        key: value
        for key, value in quote.items()
        if key not in ("version", "materials_items", "labor_estimate")
    }
    order = db.get(WorkOrder, uuid.UUID(work.rsplit("/", 1)[1]))
    order.price_estimate = legacy
    db.commit()
    approved = client.post(f"{work}/price/approve", headers=admin, json={"version": 0})
    assert approved.json()["approved_price"]["quote"] == legacy
    assert client.post(f"{work}/start", headers=tech).status_code == 200
    done = client.post(
        f"{work}/complete", headers=tech, json={"labor_cost": "500", "materials_cost": "500"}
    )
    assert done.status_code == 200 and done.json()["overrun_reason"] is None


def test_mark_all_notifications_read_is_scoped_and_ignores_inbox_limit(client, db, account, people):
    branch, outside, manager, _, outsider, technician = people
    admin = auth(account)
    inbox = "/api/notifications"
    request = client.post("/api/requests", headers=auth(manager), json=report(branch.id)).json()
    hidden = client.post("/api/requests", headers=auth(outsider), json=report(outside.id)).json()
    db.add_all(
        RequestEvent(
            request_id=uuid.UUID(request["id"]), actor_id=technician.id, action="work_completed"
        )
        for _ in range(51)
    )
    other = User(
        email="other-admin@example.com",
        full_name="Other Admin",
        role=Role.administrator,
        password_hash=account.password_hash,
    )
    db.add(other)
    db.flush()
    db.add(BranchAccess(user_id=other.id, branch_id=branch.id))
    db.commit()

    before = client.get(inbox, headers=admin).json()
    assert before["unread"] == 52 and len(before["items"]) == 50
    for _ in range(2):
        assert client.put(f"{inbox}/read", headers=admin).status_code == 204
    assert client.get(inbox, headers=admin).json()["unread"] == 0
    updates = client.get(inbox, headers=admin, params={"category": "update"}).json()["items"]
    assert len(updates) == 1 and updates[0]["read"]
    assert client.get(inbox, headers=auth(other)).json()["unread"] == 52

    db.add(BranchAccess(user_id=account.id, branch_id=outside.id))
    db.commit()
    visible = client.get(inbox, headers=admin).json()
    assert visible["unread"] == 1
    assert visible["items"][0]["request_id"] == hidden["id"] and not visible["items"][0]["read"]


def test_request_setup_saves_together_and_flags_missing_fields(client, db, account, people):
    branch, _, manager, _, _, technician = people
    admin = auth(account)
    manager_auth = auth(manager)
    queue = "/api/requests"
    db.add(ServiceCategory(id="plumbing", name="Plumbing"))
    db.commit()
    created = client.post(queue, headers=manager_auth, json=report(branch.id)).json()
    path = f"{queue}/{created['id']}"
    initial = client.get(queue, headers=admin).json()[0]
    assert initial["setup_missing"] == [
        "Priority",
        "Category",
        "Difficulty",
        "Service duration",
        "Lead technician",
        "Schedule",
        "Price estimate",
    ]
    assert client.get(path, headers=manager_auth).json()["setup_missing"] is None
    assert client.patch(f"{path}/setup", headers=manager_auth, json={}).status_code == 403

    partial = client.patch(f"{path}/setup", headers=admin, json={"priority": "high"})
    assert partial.status_code == 200
    assert "Priority" not in partial.json()["setup_missing"]
    assert "Schedule" in partial.json()["setup_missing"]
    assert "Priority" not in client.get(queue, headers=admin).json()[0]["setup_missing"]

    start = datetime.now(timezone.utc) + timedelta(days=1)
    data = {
        "priority": "urgent",
        "category": {"category_id": "plumbing"},
        "estimate": {"difficulty": "moderate", "duration_override_minutes": None},
        "team": {"technician_id": str(technician.id)},
        "schedule": {"scheduled_start": start.isoformat()},
        "price": {"hourly_rate": "200.00", "materials_estimate": "75.00"},
    }
    invalid_price = data | {"price": data["price"] | {"override": "250.00"}}
    assert client.patch(f"{path}/setup", headers=admin, json=invalid_price).status_code == 422
    unchanged = client.get(path, headers=admin).json()
    assert unchanged["priority"] == "high"
    assert unchanged["category"] is None
    assert unchanged["work_orders"] == []
    assert {event["action"] for event in unchanged["events"]} == {"submitted", "priority_changed"}

    saved = client.patch(f"{path}/setup", headers=admin, json=data)
    assert saved.status_code == 200, saved.text
    assert saved.json()["setup_missing"] == []
    detail = client.get(path, headers=admin).json()
    assert detail["setup_missing"] == []
    assert client.get(queue, headers=admin).json()[0]["setup_missing"] == []
    [order] = detail["work_orders"]
    assert order["scheduled_end"] == (start + timedelta(hours=1)).isoformat()
    assert order["price_estimate"]["amount"] == "275.00"
    assert {"work_order_assigned", "work_schedule_changed", "work_price_changed"} <= {
        event["action"] for event in detail["events"]
    }
    assert client.get(path, headers=manager_auth).json()["appointment"]["scheduled_start"] == (
        start.isoformat()
    )

    clear_schedule = {"work_order_id": order["id"], "schedule": {"scheduled_start": None}}
    assert client.patch(f"{path}/setup", headers=admin, json=clear_schedule).status_code == 200
    assert client.get(queue, headers=admin).json()[0]["setup_missing"] == ["Schedule"]
    db.add(ServiceCategory(id="carpentry", name="Carpentry"))
    db.commit()
    partial_category = client.patch(
        f"{path}/setup",
        headers=admin,
        json={
            "work_order_id": order["id"],
            "category": {"category_id": "carpentry"},
        },
    )
    assert partial_category.status_code == 200
    assert partial_category.json()["setup_missing"] == ["Service duration", "Schedule"]
    # Unchanged saved prices are snapshots, so partial planning edits need not reprice them.
    assert (
        client.get(path, headers=admin).json()["work_orders"][0]["price_estimate"]
        == order["price_estimate"]
    )


def test_categories_in_triage_and_queue(client, db, account, people):
    branch, outside, manager, _, outsider, technician = people
    admin = auth(account)
    queue = "/api/requests"
    plumbing = {"id": "plumbing", "name": "Plumbing"}
    other = {"id": "other", "name": "Other"}
    db.add_all([ServiceCategory(**plumbing), ServiceCategory(**other)])
    db.commit()

    def submit(reporter, branch_id):
        response = client.post(queue, headers=auth(reporter), json=report(branch_id))
        assert response.status_code == 201
        assert response.json()["category"] is None
        return response.json()["id"]

    request_id = submit(manager, branch.id)
    uncategorized_id = submit(manager, branch.id)
    outside_id = submit(outsider, outside.id)
    path = f"{queue}/{request_id}"

    def categorize(category_id, headers=admin, target=request_id):
        return client.patch(
            f"{queue}/{target}/category", headers=headers, json={"category_id": category_id}
        )

    def filtered(category_id):
        response = client.get(queue, headers=admin, params={"category_id": category_id})
        assert response.status_code == 200
        return {request["id"] for request in response.json()}

    assert client.get(f"{queue}/categories", headers=admin).json() == [other, plumbing]
    assert client.get(f"{queue}/categories", headers=auth(manager)).status_code == 403
    assert categorize("plumbing", auth(manager)).status_code == 403
    assert categorize("plumbing", auth(technician)).status_code == 403
    assert categorize("plumbing", target=outside_id).status_code == 404
    assert categorize("invalid").status_code == 422
    assert categorize("plumbing").json()["category"] == plumbing
    assert categorize("plumbing").status_code == 200
    assert filtered("plumbing") == {request_id}
    assert filtered("uncategorized") == {uncategorized_id}
    assert categorize(None).json()["category"] is None
    assert filtered("uncategorized") == {request_id, uncategorized_id}
    assert categorize("other").json()["category"] == other

    detail = client.get(path, headers=auth(manager)).json()
    assert detail["category"] == other
    changes = [
        event["details"] for event in detail["events"] if event["action"] == "category_changed"
    ]
    assert len(changes) == 3
    for change in [
        {"from": None, "to": "Plumbing"},
        {"from": "Plumbing", "to": None},
        {"from": None, "to": "Other"},
    ]:
        assert change in changes

    request = db.get(ServiceRequest, uuid.UUID(request_id))
    request.status = RequestStatus.closed
    db.commit()
    assert categorize("plumbing").status_code == 409
    assert client.get(path, headers=admin).json()["category"] == other


def test_service_estimates_recalculate_and_preserve_manual_duration(client, db, account, people):
    branch, outside, manager, _, outsider, technician = people
    admin = auth(account)
    queue = "/api/requests"
    db.add_all(
        [
            ServiceCategory(id="plumbing", name="Plumbing"),
            ServiceCategory(id="electrical", name="Electrical"),
        ]
    )
    db.commit()

    def submit(reporter, branch_id):
        response = client.post(queue, headers=auth(reporter), json=report(branch_id))
        assert response.status_code == 201
        assert response.json()["difficulty"] is None
        assert response.json()["estimated_duration_minutes"] is None
        return response.json()["id"]

    request_id = submit(manager, branch.id)
    outside_id = submit(outsider, outside.id)
    path = f"{queue}/{request_id}"

    def estimate(difficulty, minutes, headers=admin, target=request_id):
        return client.patch(
            f"{queue}/{target}/estimate",
            headers=headers,
            json={"difficulty": difficulty, "duration_override_minutes": minutes},
        )

    def category(category_id):
        response = client.patch(
            f"{path}/category", headers=admin, json={"category_id": category_id}
        )
        assert response.status_code == 200
        return response.json()

    assert estimate("moderate", 90, auth(manager)).status_code == 403
    assert estimate("moderate", 90, auth(technician)).status_code == 403
    assert estimate("moderate", 90, target=outside_id).status_code == 404
    assert estimate("urgent", None).status_code == 422
    for invalid in (0, 10081, 2.5, "90", True):
        assert estimate("moderate", invalid).status_code == 422

    assert estimate(None, 45).json()["estimated_duration_minutes"] == 45
    assert estimate("moderate", None).json()["estimated_duration_minutes"] is None
    assert category("plumbing")["estimated_duration_minutes"] == 60
    assert estimate("hard", None).json()["estimated_duration_minutes"] == 120
    assert estimate("hard", 90).json()["estimated_duration_minutes"] == 90
    assert estimate("hard", 90).status_code == 200
    assert estimate("moderate", 90).json()["estimated_duration_minutes"] == 90
    changed = category("electrical")
    assert changed["suggested_duration_minutes"] == 75
    assert changed["estimated_duration_minutes"] == 90
    assert category(None)["estimated_duration_minutes"] == 90
    category("electrical")
    assert estimate("moderate", None).json()["estimated_duration_minutes"] == 75

    detail = client.get(path, headers=auth(manager)).json()
    assert detail["duration_suggestions"] == {"easy": 30, "moderate": 75, "hard": 150}
    assert detail["difficulty"] == "moderate"
    assert detail["estimated_duration_minutes"] == 75
    changes = [
        event["details"] for event in detail["events"] if event["action"] == "estimate_changed"
    ]
    assert len(changes) == 6
    assert {
        "previous": {"difficulty": "moderate", "duration_override_minutes": 90},
        "updated": {"difficulty": "moderate", "duration_override_minutes": None},
    } in changes

    request = db.get(ServiceRequest, uuid.UUID(request_id))
    request.status = RequestStatus.closed
    db.commit()
    assert estimate("easy", None).status_code == 409
    assert client.get(path, headers=admin).json()["estimated_duration_minutes"] == 75


def test_team_scheduling_pricing_and_verification(client, db, account, people):
    branch, outside, manager, _, _, lead = people
    admin = auth(account)

    def technician(name, branch_id):
        member = User(
            email=f"{name}@example.com",
            full_name=name,
            role=Role.technician,
            password_hash=account.password_hash,
        )
        db.add(member)
        db.flush()
        db.add(BranchAccess(user_id=member.id, branch_id=branch_id))
        db.commit()
        return member

    assistant = technician("Assistant", branch.id)
    second_lead = technician("Second", branch.id)
    outsider = technician("Outside", outside.id)

    def request_path():
        response = client.post("/api/requests", headers=auth(manager), json=report(branch.id))
        assert response.status_code == 201
        return f"/api/requests/{response.json()['id']}"

    def assign(path, technician_id, *assistants):
        return client.post(
            f"{path}/work-orders",
            headers=admin,
            json={
                "technician_id": str(technician_id),
                "assistant_ids": [str(member.id) for member in assistants],
            },
        )

    first, second = request_path(), request_path()
    assert assign(first, lead.id, lead).status_code == 422
    assert assign(first, lead.id, outsider).status_code == 422
    assigned = assign(first, lead.id, assistant)
    assert assigned.status_code == 201
    assert assigned.json()["assistants"] == [{"id": str(assistant.id), "full_name": "Assistant"}]
    first_id = assigned.json()["id"]
    first_order = f"{first}/work-orders/{first_id}"
    assigned = assign(second, second_lead.id, assistant)
    assert assigned.status_code == 201
    second_order = f"{second}/work-orders/{assigned.json()['id']}"

    def patch(order, action, **fields):
        return client.patch(f"{order}/{action}", headers=admin, json=fields)

    local_zone = timezone(timedelta(hours=8))
    now = datetime.now(local_zone)
    start = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=90)
    slot = start.isoformat()
    assert patch(first_order, "schedule", scheduled_start=slot).status_code == 422
    assert (
        client.patch(
            first + "/estimate",
            headers=admin,
            json={"difficulty": None, "duration_override_minutes": 90},
        ).status_code
        == 200
    )
    scheduled = patch(first_order, "schedule", scheduled_start=slot)
    assert scheduled.status_code == 200
    assert scheduled.json()["scheduled_end"] == end.astimezone(timezone.utc).isoformat()
    past = patch(first_order, "schedule", scheduled_start=(now - timedelta(minutes=1)).isoformat())
    assert past.status_code == 422
    assert past.json()["detail"] == "Choose a planned start time in the future"
    appointment = client.get(first, headers=auth(manager)).json()["appointment"]
    assert appointment["scheduled_start"] == start.astimezone(timezone.utc).isoformat()
    assert (
        patch(second_order, "schedule", scheduled_start=slot, duration_minutes=60).status_code
        == 409
    )
    assert patch(second_order, "team", assistant_ids=[]).status_code == 200
    assert (
        patch(second_order, "schedule", scheduled_start=slot, duration_minutes=60).status_code
        == 200
    )
    assert patch(second_order, "team", assistant_ids=[str(assistant.id)]).status_code == 409
    assert (
        client.post(
            f"{second_order}/reassign",
            headers=admin,
            json={
                "previous_technician_id": str(second_lead.id),
                "technician_id": str(assistant.id),
                "reason": "Shift change",
            },
        ).status_code
        == 409
    )
    assert (
        patch(
            second_order,
            "schedule",
            scheduled_start=end.isoformat(),
            duration_minutes=60,
        ).status_code
        == 200
    )
    assert patch(second_order, "team", assistant_ids=[str(assistant.id)]).status_code == 200
    assert patch(second_order, "schedule", scheduled_start=None).json()["scheduled_start"] is None

    price = {"hourly_rate": "200", "materials_estimate": "75"}
    assert patch(first_order, "price", **price).json()["price_estimate"]["amount"] == "675.00"
    assert patch(first_order, "price", **price, override="650").status_code == 422
    quote = patch(first_order, "price", **price, override="650", reason="Approved discount")
    assert quote.json()["price_estimate"]["amount"] == "650.00"
    assert quote.json()["price_estimate"]["suggested"] == "675.00"

    assistant_auth = auth(assistant)
    assert client.get(first, headers=assistant_auth).json()["work_orders"][0]["id"] == first_id
    assert "work_schedule_changed" in {
        item["action"]
        for item in client.get("/api/notifications", headers=assistant_auth).json()["items"]
    }
    assert client.post(f"{first_order}/start", headers=assistant_auth).status_code == 403
    assert client.post(f"{first_order}/start", headers=auth(lead)).status_code == 200
    log = client.post(
        f"{first_order}/logs",
        headers=assistant_auth,
        json={"action": "Replaced seal", "notes": "Checked for leaks after replacement."},
    )
    assert log.status_code == 201
    assert log.json()["recorded_by_name"] == "Assistant"
    actual = {"labor_cost": "280", "materials_cost": "70"}
    assert (
        client.post(f"{first_order}/complete", headers=assistant_auth, json=actual).status_code
        == 403
    )
    assert (
        client.post(f"{first_order}/complete", headers=auth(lead), json=actual).status_code == 200
    )
    assert patch(first_order, "price", **price).status_code == 409
    review = client.post(f"{first}/verify", headers=admin, json={"work_order_id": first_id})
    assert review.status_code == 200
    assert review.json()["status"] == "closed"


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
    for changes in [{"title": "  "}, {"description": " "}, {"location": " "}]:
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


def test_technician_specialization_management_and_assignment(client, db, account, people):
    branch, outside, manager, _, _, technician = people
    admin = auth(account)
    db.add(ServiceCategory(id="plumbing", name="Plumbing"))
    db.commit()

    payload = {
        "full_name": "Avery Technician",
        "email": "avery@example.com",
        "password": "technician-password",
        "role": "technician",
        "branch_ids": [str(branch.id)],
        "specialization": "plumbing",
    }
    response = client.post("/api/admin/users", headers=admin, json=payload)
    assert response.status_code == 201
    assert response.json()["specialization"] == "plumbing"
    specialist_id = response.json()["id"]
    specialist_path = f"/api/admin/users/{specialist_id}/specialization"
    assert (
        client.patch(specialist_path, headers=admin, json={"specialization": "unknown"}).status_code
        == 422
    )
    assert (
        client.patch(
            specialist_path, headers=auth(manager), json={"specialization": None}
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/admin/users/{manager.id}/specialization",
            headers=admin,
            json={"specialization": "plumbing"},
        ).status_code
        == 422
    )

    technician.specialization = "Plumbing"
    db.commit()
    request = client.post("/api/requests", headers=auth(manager), json=report(branch.id)).json()
    path = f"/api/requests/{request['id']}"
    assert (
        client.patch(
            f"{path}/category", headers=admin, json={"category_id": "plumbing"}
        ).status_code
        == 200
    )

    def options():
        return client.get(path, headers=admin).json()["eligible_technicians"]

    assert [option["id"] for option in options()] == [specialist_id, str(technician.id)]
    assert all(
        option["matches_category"] and option["specialization"] == "Plumbing"
        for option in options()
    )
    cleared = client.patch(specialist_path, headers=admin, json={"specialization": None})
    assert cleared.status_code == 200
    assert cleared.json()["specialization"] is None
    assert [option["id"] for option in options()] == [str(technician.id), specialist_id]

    db.add(BranchAccess(user_id=uuid.UUID(specialist_id), branch_id=outside.id))
    db.commit()
    assert (
        client.patch(
            specialist_path, headers=admin, json={"specialization": "plumbing"}
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"{path}/work-orders", headers=admin, json={"technician_id": specialist_id}
        ).status_code
        == 201
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
        {
            "id": str(technician.id),
            "full_name": technician.full_name,
            "specialization": None,
            "matches_category": False,
        }
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
        {
            "id": str(technician.id),
            "full_name": technician.full_name,
            "specialization": None,
            "matches_category": False,
        }
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
    assert submitted["items"][0]["category"] == "update"
    assert client.get(inbox, headers=admin, params={"category": "update"}).json() == submitted
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
    approvals = client.get(inbox, headers=admin, params={"category": "approval"}).json()
    assert approvals["unread"] == 1
    [approval] = approvals["items"]
    assert approval["category"] == "approval"
    assert client.get(inbox, headers=admin, params={"category": "completed"}).json()["items"] == []
    manager_completed = client.get(inbox, headers=manager_auth, params={"category": "completed"})
    assert [item["action"] for item in manager_completed.json()["items"]] == ["work_completed"]
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
    current = client.get(inbox, headers=admin, params={"category": "approval"}).json()
    [pending_review] = current["items"]
    assert pending_review["id"] != approval["id"]
    assert current["unread"] == 2
    assert client.put(f"{inbox}/{pending_review['id']}/read", headers=admin).status_code == 204
    marked = client.get(inbox, headers=admin, params={"category": "approval"}).json()
    assert marked["unread"] == 1 and marked["items"][0]["read"]
    assert client.post(f"{path}/verify", headers=admin, json=review).status_code == 409
    closed = client.post(
        f"{path}/verify",
        headers=admin,
        json={"work_order_id": follow_up["id"], "notes": "Passed under load"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert client.get(inbox, headers=admin, params={"category": "approval"}).json()["items"] == []
    finished = client.get(inbox, headers=admin, params={"category": "completed"}).json()["items"]
    assert {item["id"] for item in finished} == {approval["id"], pending_review["id"]}
    saved = db.get(ServiceRequest, uuid.UUID(created["id"]))
    assert saved.closed_by == account.id and saved.closed_at is not None
    detail = client.get(path, headers=admin).json()
    assert [item["id"] for item in detail["work_orders"]] == [order["id"], follow_up["id"]]
    assert detail["maintenance_logs"] == [log.json()]
    manager_events = client.get(path, headers=auth(manager)).json()["events"]
    assert any(event["details"].get("reason") == "Retest under load" for event in manager_events)
    assert any(event["details"].get("notes") == "Passed under load" for event in manager_events)

    report_url = "/api/reports/repairs"
    day = saved.closed_at.date()
    dates = {"start_date": day.isoformat(), "end_date": day.isoformat()}
    # The original order and follow-up can finish on different reporting days.
    first_completion = db.scalar(
        select(RequestEvent).where(
            RequestEvent.request_id == saved.id,
            RequestEvent.action == "work_completed",
            RequestEvent.details["work_order_id"].as_string() == order["id"],
        )
    )
    first_completion.created_at = saved.closed_at - timedelta(days=1)
    follow_up_completion = db.scalar(
        select(RequestEvent).where(
            RequestEvent.request_id == saved.id,
            RequestEvent.action == "work_completed",
            RequestEvent.details["work_order_id"].as_string() == follow_up["id"],
        )
    )
    follow_up_completion.created_at = saved.closed_at
    db.commit()
    summary = client.get(report_url, headers=admin, params=dates).json()
    assert summary["totals"] == {
        "closed_requests": 1,
        "completed_orders": 1,
        "labor_cost": "120.25",
        "materials_cost": "0.00",
        "total_cost": "120.25",
    }
    assert [row["branch_id"] for row in summary["branches"]] == [str(branch.id)]
    wider = client.get(
        report_url,
        headers=admin,
        params=dates
        | {"branch_id": branch.id, "start_date": (day - timedelta(days=1)).isoformat()},
    )
    assert wider.json()["totals"] == summary["totals"] | {
        "completed_orders": 2,
        "labor_cost": "240.50",
        "total_cost": "240.50",
    }
    assert client.get(report_url, headers=tech, params=dates).status_code == 403
    assert (
        client.get(
            report_url, headers=admin, params=dates | {"start_date": "9999-12-31"}
        ).status_code
        == 422
    )
    db.delete(db.get(BranchAccess, (account.id, branch.id)))
    db.commit()
    assert client.get(report_url, headers=admin, params=dates).json()["branches"] == []
    assert (
        client.get(report_url, headers=admin, params=dates | {"branch_id": branch.id}).status_code
        == 404
    )


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
