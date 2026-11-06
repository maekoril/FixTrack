import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["JWT_SECRET"] = "test-secret-only-do-not-use-in-production-123456789"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.db import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Branch, BranchAccess, Role, User  # noqa: E402
from app.security import password_hash  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def account(db):
    branch = Branch(name="Branch A", location="Laguna")
    hidden = Branch(name="Branch B", location="Manila")
    user = User(
        email="admin@example.com",
        full_name="Test Admin",
        role=Role.administrator,
        password_hash=password_hash.hash("correct-password"),
    )
    db.add_all([branch, hidden, user])
    db.flush()
    db.add(BranchAccess(user_id=user.id, branch_id=branch.id))
    db.commit()
    return user


@pytest.fixture
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
