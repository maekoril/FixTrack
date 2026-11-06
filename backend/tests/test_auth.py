from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import get_settings
from app.models import Role
from app.security import issue_token


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_login_and_profile(client, account):
    response = client.post(
        "/api/auth/login", json={"email": "ADMIN@example.com", "password": "correct-password"}
    )
    assert response.status_code == 200
    token = response.json()["access_token"]
    profile = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert profile.json()["id"] == str(account.id)
    assert "password_hash" not in profile.json()


@pytest.mark.parametrize(
    "email,password", [("admin@example.com", "wrong"), ("missing@example.com", "wrong")]
)
def test_invalid_credentials(client, account, email, password):
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password"


@pytest.mark.parametrize("role", list(Role))
def test_all_roles_only_see_granted_branches(client, account, db, role):
    account.role = role
    db.commit()
    response = client.get(
        "/api/branches", headers={"Authorization": f"Bearer {issue_token(account)}"}
    )
    assert response.status_code == 200
    assert [branch["name"] for branch in response.json()] == ["Branch A"]


def test_disabled_account_cannot_login_or_reuse_token(client, account, db):
    token = issue_token(account)
    account.is_active = False
    db.commit()
    assert (
        client.post(
            "/api/auth/login", json={"email": account.email, "password": "correct-password"}
        ).status_code
        == 401
    )
    assert (
        client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    )


@pytest.mark.parametrize("token", [None, "malformed", "expired", "forged"])
def test_invalid_token(client, account, token):
    now = datetime.now(timezone.utc)
    if token in ("expired", "forged"):
        token = jwt.encode(
            {
                "sub": str(account.id),
                "iat": now - timedelta(hours=2),
                "exp": now - timedelta(hours=1) if token == "expired" else now + timedelta(hours=1),
            },
            get_settings().jwt_secret if token == "expired" else "x" * 48,
            algorithm="HS256",
        )
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    assert client.get("/api/auth/me", headers=headers).status_code == 401
