import uuid

import pytest
from sqlalchemy import select

from app.models import Branch, BranchAccess, Role, ServiceRequest, User, WorkOrder
from app.security import issue_token


def headers(account):
    return {"Authorization": f"Bearer {issue_token(account)}"}


def payload(branch_id, **overrides):
    return {
        "email": "worker@example.com",
        "full_name": "Worker",
        "password": "safe-password-123",
        "role": "branch_manager",
        "branch_ids": [str(branch_id)],
        **overrides,
    }


@pytest.mark.parametrize("role", [Role.branch_manager, Role.technician])
def test_non_admin_cannot_use_admin_routes(client, account, db, role):
    account.role = role
    db.commit()
    auth = headers(account)
    assert client.get("/api/admin/users", headers=auth).status_code == 403
    assert (
        client.post(
            "/api/admin/branches", headers=auth, json={"name": "C", "location": "Office"}
        ).status_code
        == 403
    )
    assert (
        client.post("/api/admin/users", headers=auth, json=payload(uuid.uuid4())).status_code == 403
    )
    assert (
        client.patch(
            f"/api/admin/users/{uuid.uuid4()}/active", headers=auth, json={"is_active": False}
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/api/admin/users/{uuid.uuid4()}/branches",
            headers=auth,
            json={"branch_ids": [str(uuid.uuid4())]},
        ).status_code
        == 403
    )


def test_branch_creation_grants_access_and_duplicate_conflicts(client, account):
    auth = headers(account)
    data = {"name": "New Branch", "location": "Laguna"}
    response = client.post("/api/admin/branches", headers=auth, json=data)
    assert response.status_code == 201
    assert response.json()["id"] in [
        b["id"] for b in client.get("/api/branches", headers=auth).json()
    ]
    assert client.post("/api/admin/branches", headers=auth, json=data).status_code == 409


def test_create_user_login_disable_and_reenable(client, account, db):
    auth = headers(account)
    branch_id = db.scalar(select(BranchAccess.branch_id).where(BranchAccess.user_id == account.id))
    response = client.post("/api/admin/users", headers=auth, json=payload(branch_id))
    assert response.status_code == 201
    user = response.json()
    assert "password" not in user and "password_hash" not in user
    assert client.post("/api/admin/users", headers=auth, json=payload(branch_id)).status_code == 409
    login = {"email": "worker@example.com", "password": "safe-password-123"}
    token = client.post("/api/auth/login", json=login).json()["access_token"]
    assert (
        client.patch(
            f"/api/admin/users/{user['id']}/active", headers=auth, json={"is_active": False}
        ).status_code
        == 200
    )
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )
    assert client.post("/api/auth/login", json=login).status_code == 401
    assert (
        client.patch(
            f"/api/admin/users/{user['id']}/active", headers=auth, json={"is_active": True}
        ).status_code
        == 200
    )
    assert client.post("/api/auth/login", json=login).status_code == 200


def test_scope_and_administrator_protection(client, account, db):
    auth = headers(account)
    outside = db.scalar(select(Branch).where(Branch.name == "Branch B"))
    assert (
        client.post("/api/admin/users", headers=auth, json=payload(outside.id)).status_code == 403
    )
    assert (
        client.post(
            "/api/admin/users", headers=auth, json=payload(outside.id, role="administrator")
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/admin/users/{account.id}/active", headers=auth, json={"is_active": False}
        ).status_code
        == 404
    )
    target = User(
        email="outside@example.com",
        full_name="Outside",
        role=Role.technician,
        password_hash=account.password_hash,
    )
    db.add(target)
    db.flush()
    db.add(BranchAccess(user_id=target.id, branch_id=outside.id))
    db.commit()
    assert client.get("/api/admin/users", headers=auth).json() == []
    assert (
        client.patch(
            f"/api/admin/users/{target.id}/active", headers=auth, json={"is_active": False}
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/admin/users/{target.id}/branches",
            headers=auth,
            json={"branch_ids": [str(outside.id)]},
        ).status_code
        == 404
    )


def test_branch_manager_can_be_granted_multiple_branches(client, account, db):
    auth = headers(account)
    first = db.scalar(select(BranchAccess.branch_id).where(BranchAccess.user_id == account.id))
    second = client.post(
        "/api/admin/branches", headers=auth, json={"name": "New", "location": "Office"}
    ).json()["id"]
    response = client.post("/api/admin/users", headers=auth, json=payload(first))
    user_id = response.json()["id"]
    path = f"/api/admin/users/{user_id}/branches"
    assert client.put(path, headers=auth, json={"branch_ids": []}).status_code == 422
    changed = client.put(path, headers=auth, json={"branch_ids": [str(first), second]})
    assert changed.status_code == 200
    assert set(changed.json()["branch_ids"]) == {str(first), second}
    assert (
        client.put(path, headers=auth, json={"branch_ids": [str(uuid.uuid4())]}).status_code == 403
    )
    assert client.put(path, headers=auth, json={"branch_ids": [second]}).json()["branch_ids"] == [
        second
    ]
    assert (
        client.post(
            "/api/admin/users",
            headers=auth,
            json=payload(
                first, email="tech@example.com", role="technician", branch_ids=[str(first), second]
            ),
        ).status_code
        == 201
    )


def test_whitespace_and_short_password_rejected(client, account, db):
    auth = headers(account)
    branch = db.scalar(select(BranchAccess.branch_id).where(BranchAccess.user_id == account.id))
    assert (
        client.post(
            "/api/admin/branches", headers=auth, json={"name": "  ", "location": "Office"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/admin/users", headers=auth, json=payload(branch, password="short")
        ).status_code
        == 422
    )


@pytest.mark.parametrize("managed_role", ["branch_manager", "technician"])
def test_account_crud_and_deleted_token_rejected(client, account, db, managed_role):
    auth = headers(account)
    branch = db.scalar(select(BranchAccess.branch_id).where(BranchAccess.user_id == account.id))
    created = client.post("/api/admin/users", headers=auth, json=payload(branch, role=managed_role))
    assert created.status_code == 201
    user_id = created.json()["id"]
    path = f"/api/admin/users/{user_id}"
    token = client.post(
        "/api/auth/login",
        json={"email": "worker@example.com", "password": "safe-password-123"},
    ).json()["access_token"]
    changed = client.patch(
        path, headers=auth, json={"full_name": "  Updated Worker  ", "email": "Updated@EXAMPLE.COM"}
    )
    assert changed.status_code == 200
    assert changed.json()["full_name"] == "Updated Worker"
    assert changed.json()["email"] == "updated@example.com"
    assert changed.json()["role"] == managed_role
    assert changed.json()["branch_ids"] == [str(branch)]
    assert "password_hash" not in changed.json()
    assert client.get("/api/admin/users", headers=auth).json() == [changed.json()]
    assert (
        client.post(
            "/api/auth/login",
            json={"email": "updated@example.com", "password": "safe-password-123"},
        ).status_code
        == 200
    )
    removed = client.delete(path, headers=auth)
    assert removed.status_code == 204 and removed.content == b""
    assert client.get("/api/admin/users", headers=auth).json() == []
    assert db.get(User, uuid.UUID(user_id)) is None
    assert db.scalar(select(BranchAccess).where(BranchAccess.user_id == uuid.UUID(user_id))) is None
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )


def test_profile_duplicate_and_invalid_edits_are_atomic(client, account, db):
    auth = headers(account)
    branch = db.scalar(select(BranchAccess.branch_id).where(BranchAccess.user_id == account.id))
    user = client.post("/api/admin/users", headers=auth, json=payload(branch)).json()
    path = f"/api/admin/users/{user['id']}"
    assert (
        client.patch(
            path, headers=auth, json={"full_name": "Must roll back", "email": account.email}
        ).status_code
        == 409
    )
    assert client.get("/api/admin/users", headers=auth).json() == [user]
    for invalid in [
        {"full_name": " ", "email": "worker@example.com"},
        {"full_name": "Worker", "email": "invalid"},
        {"full_name": "Worker", "email": "worker@example.com", "role": "administrator"},
    ]:
        assert client.patch(path, headers=auth, json=invalid).status_code == 422


@pytest.mark.parametrize("history", ["reported", "assigned"])
def test_delete_account_with_history_preserves_records_and_grants(client, account, db, history):
    auth = headers(account)
    branch = db.scalar(select(BranchAccess.branch_id).where(BranchAccess.user_id == account.id))
    role = "technician" if history == "assigned" else "branch_manager"
    user = client.post("/api/admin/users", headers=auth, json=payload(branch, role=role)).json()
    user_id = uuid.UUID(user["id"])
    request = ServiceRequest(
        branch_id=branch,
        submitted_by=user_id if history == "reported" else account.id,
        title="Broken light",
        description="Light will not turn on",
        location="Room 101",
    )
    db.add(request)
    db.flush()
    if history == "assigned":
        db.add(WorkOrder(request_id=request.id, technician_id=user_id, assigned_by=account.id))
    db.commit()
    response = client.delete(f"/api/admin/users/{user_id}", headers=auth)
    assert response.status_code == 409
    assert "Disable" in response.json()["detail"]
    assert db.get(ServiceRequest, request.id) is not None
    if history == "assigned":
        assert (
            db.scalar(select(WorkOrder).where(WorkOrder.request_id == request.id)).technician_id
            == user_id
        )
    else:
        assert db.get(ServiceRequest, request.id).submitted_by == user_id
    assert db.get(User, user_id).is_active
    assert db.scalar(select(BranchAccess).where(BranchAccess.user_id == user_id)) is not None
    assert (
        client.patch(
            f"/api/admin/users/{user_id}/active", headers=auth, json={"is_active": False}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("actor_role", [Role.branch_manager, Role.technician])
def test_profile_and_delete_require_administrator(client, account, db, actor_role):
    account.role = actor_role
    db.commit()
    auth = headers(account)
    path = f"/api/admin/users/{account.id}"
    assert (
        client.patch(
            path, headers=auth, json={"full_name": "Edited", "email": "edit@example.com"}
        ).status_code
        == 403
    )
    assert client.delete(path, headers=auth).status_code == 403


def test_profile_and_delete_protect_admins_and_out_of_scope_accounts(client, account, db):
    auth = headers(account)
    outside = db.scalar(select(Branch).where(Branch.name == "Branch B"))
    target = User(
        email="outside@example.com",
        full_name="Outside",
        role=Role.technician,
        password_hash=account.password_hash,
    )
    db.add(target)
    db.flush()
    db.add(BranchAccess(user_id=target.id, branch_id=outside.id))
    db.commit()
    for user_id in [account.id, target.id, uuid.uuid4()]:
        path = f"/api/admin/users/{user_id}"
        assert (
            client.patch(
                path, headers=auth, json={"full_name": "Edited", "email": "edit@example.com"}
            ).status_code
            == 404
        )
        assert client.delete(path, headers=auth).status_code == 404
