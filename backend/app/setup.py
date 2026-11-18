from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, EmailStr, SecretStr, StringConstraints
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Branch, BranchAccess, Role, User
from app.security import password_hash

router = APIRouter(prefix="/api/setup")


class SetupInput(BaseModel):
    email: EmailStr
    full_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)
    ]
    branch: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
    password: SecretStr


def lock_admin_provisioning(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SET LOCAL lock_timeout = '5s'"))
        db.execute(text("LOCK TABLE users IN SHARE ROW EXCLUSIVE MODE"))


def provision_admin(
    db: Session, *, email: str, full_name: str, branch_name: str, location: str, password: str
) -> None:
    branch = db.scalar(select(Branch).where(Branch.name == branch_name))
    if branch is None:
        branch = Branch(name=branch_name, location=location)
        db.add(branch)
        db.flush()
    user = User(
        email=email,
        full_name=full_name,
        role=Role.administrator,
        password_hash=password_hash.hash(password),
    )
    db.add(user)
    db.flush()
    db.add(BranchAccess(user_id=user.id, branch_id=branch.id))


@router.post("/admin", status_code=201)
def create_first_admin(
    data: SetupInput,
    db: Session = Depends(get_db),
    setup_token: Annotated[str, Header(alias="X-Setup-Token")] = "",
):
    expected = get_settings().setup_token
    if expected is None:
        raise HTTPException(404, "Browser setup is disabled. Set SETUP_TOKEN and restart the API.")
    if not compare_digest(setup_token.encode(), expected.encode()):
        raise HTTPException(403, "Invalid setup token.")
    password = data.password.get_secret_value()
    if not 12 <= len(password) <= 1024:
        raise HTTPException(422, "Use a password between 12 and 1024 characters.")

    email = str(data.email).lower()
    try:
        with db.begin():
            lock_admin_provisioning(db)
            if db.scalar(select(User.id).where(User.role == Role.administrator).limit(1)):
                raise HTTPException(409, "An administrator already exists. Sign in to FixTrack.")
            if db.scalar(select(User.id).where(User.email == email)):
                raise HTTPException(409, "That email is already in use.")
            provision_admin(
                db,
                email=email,
                full_name=data.full_name,
                branch_name=data.branch,
                location=data.location,
                password=password,
            )
    except SQLAlchemyError as exc:
        raise HTTPException(
            503, "Database setup could not complete. Check PostgreSQL and apply migrations."
        ) from exc
    return {"status": "created"}
