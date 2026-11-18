from sqlalchemy.exc import OperationalError

from app import setup
from app.config import get_settings

TOKEN = "test-setup-token-12345678901234567890"
ADMIN = {
    "email": "owner@example.com",
    "full_name": "First Admin",
    "branch": "Head Office",
    "location": "Laguna",
    "password": "a-long-test-password",
}


def test_setup_disabled_by_default(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "setup_token", None)
    assert client.post("/api/setup/admin", json=ADMIN).status_code == 404


def test_setup_reports_database_failure(client, monkeypatch):
    def unavailable(_db):
        raise OperationalError(None, None, RuntimeError("connection timed out"))

    monkeypatch.setattr(get_settings(), "setup_token", TOKEN)
    monkeypatch.setattr(setup, "lock_admin_provisioning", unavailable)
    response = client.post("/api/setup/admin", headers={"X-Setup-Token": TOKEN}, json=ADMIN)
    assert response.status_code == 503
    assert "Check PostgreSQL" in response.json()["detail"]


def test_first_admin_setup(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "setup_token", TOKEN)
    path = "/api/setup/admin"
    headers = {"X-Setup-Token": TOKEN}
    assert client.post(path, json=ADMIN).status_code == 403
    assert (
        client.post(path, headers=headers, json={**ADMIN, "password": "short"}).status_code == 422
    )
    assert client.post(path, headers=headers, json=ADMIN).status_code == 201
    assert (
        client.post(path, headers=headers, json={**ADMIN, "email": "other@example.com"}).status_code
        == 409
    )

    login = client.post(
        "/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}
    )
    assert login.status_code == 200
    auth = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=auth).json()["role"] == "administrator"
    branches = client.get("/api/branches", headers=auth).json()
    assert [(branch["name"], branch["location"]) for branch in branches] == [
        ("Head Office", "Laguna")
    ]
