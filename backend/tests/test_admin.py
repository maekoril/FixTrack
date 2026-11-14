import uuid

import pytest
from sqlalchemy import select

from app.models import Branch, BranchAccess, Role, User
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
