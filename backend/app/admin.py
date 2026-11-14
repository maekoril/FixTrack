import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typing_extensions import Annotated

from app.db import get_db
from app.models import Branch, BranchAccess, Role, User
from app.security import current_user, password_hash

router = APIRouter(prefix="/api/admin", tags=["Administration"])
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


def administrator(user: User = Depends(current_user)) -> User:
    if user.role != Role.administrator:
        raise HTTPException(403, "Administrator access required")
    return user


def branch_ids(db: Session, user_id: uuid.UUID) -> set[uuid.UUID]:
    return set(db.scalars(select(BranchAccess.branch_id).where(BranchAccess.user_id == user_id)))


class BranchInput(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    location: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]


class BranchOutput(BranchInput):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID


class UserInput(BaseModel):
    full_name: Name
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    role: Literal["branch_manager", "technician"]
    branch_ids: list[uuid.UUID] = Field(min_length=1)


class AccessInput(BaseModel):
    branch_ids: list[uuid.UUID] = Field(min_length=1)


class ActiveInput(BaseModel):
    is_active: bool


class UserOutput(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    role: Role
    is_active: bool
    branch_ids: list[uuid.UUID]


def output(db: Session, user: User) -> UserOutput:
    return UserOutput(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        branch_ids=sorted(branch_ids(db, user.id)),
    )


def validate_access(ids: list[uuid.UUID], scope: set[uuid.UUID]):
    if not set(ids) <= scope:
        raise HTTPException(403, "You can only grant access to your own branches")


def managed_user(db: Session, actor: User, user_id: uuid.UUID) -> User:
    target = db.get(User, user_id)
    if target is None or target.role == Role.administrator:
        raise HTTPException(404, "Managed user not found")
    grants = branch_ids(db, target.id)
    if not grants or not grants <= branch_ids(db, actor.id):
        raise HTTPException(404, "Managed user not found")
    return target


def commit(db: Session):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That email or branch name already exists") from None


@router.post("/branches", response_model=BranchOutput, status_code=201)
def create_branch(
    data: BranchInput, actor: User = Depends(administrator), db: Session = Depends(get_db)
):
    branch = Branch(**data.model_dump())
    db.add(branch)
    try:
        db.flush()
        db.add(BranchAccess(user_id=actor.id, branch_id=branch.id))
        commit(db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That branch name already exists") from None
    return branch


@router.get("/users", response_model=list[UserOutput])
def users(actor: User = Depends(administrator), db: Session = Depends(get_db)):
    scope = branch_ids(db, actor.id)
    # A branch admin cannot manage a technician who also works outside their scope.
    candidates = db.scalars(
        select(User).where(User.role != Role.administrator).order_by(User.full_name)
    ).all()
    return [
        output(db, user)
        for user in candidates
        if (grants := branch_ids(db, user.id)) and grants <= scope
    ]


@router.post("/users", response_model=UserOutput, status_code=201)
def create_user(
    data: UserInput, actor: User = Depends(administrator), db: Session = Depends(get_db)
):
    validate_access(data.branch_ids, branch_ids(db, actor.id))
    user = User(
        full_name=data.full_name,
        email=str(data.email).lower(),
        role=Role(data.role),
        password_hash=password_hash.hash(data.password),
    )
    db.add(user)
    try:
        db.flush()
        db.add_all(
            [
                BranchAccess(user_id=user.id, branch_id=branch_id)
                for branch_id in set(data.branch_ids)
            ]
        )
        commit(db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "That email already exists") from None
    return output(db, user)


@router.put("/users/{user_id}/branches", response_model=UserOutput)
def update_access(
    user_id: uuid.UUID,
    data: AccessInput,
    actor: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    user = managed_user(db, actor, user_id)
    validate_access(data.branch_ids, branch_ids(db, actor.id))
    existing = db.scalars(select(BranchAccess).where(BranchAccess.user_id == user.id)).all()
    wanted = set(data.branch_ids)
    current = {grant.branch_id for grant in existing}
    for grant in existing:
        if grant.branch_id not in wanted:
            db.delete(grant)
    db.add_all(
        [BranchAccess(user_id=user.id, branch_id=branch_id) for branch_id in wanted - current]
    )
    commit(db)
    return output(db, user)


@router.patch("/users/{user_id}/active", response_model=UserOutput)
def update_active(
    user_id: uuid.UUID,
    data: ActiveInput,
    actor: User = Depends(administrator),
    db: Session = Depends(get_db),
):
    user = managed_user(db, actor, user_id)
    user.is_active = data.is_active
    commit(db)
    return output(db, user)
