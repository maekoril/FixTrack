import uuid

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.admin import router as admin_router
from app.assets import router as assets_router
from app.config import get_settings
from app.db import get_db
from app.models import Branch, BranchAccess, Role, User
from app.notifications import router as notifications_router
from app.photos import router as photos_router
from app.requests import router as requests_router
from app.security import current_user, dummy_hash, issue_token, password_hash
from app.setup import router as setup_router

app = FastAPI(title="FixTrack API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Setup-Token"],
)
app.include_router(admin_router)
app.include_router(assets_router)
app.include_router(requests_router)
app.include_router(notifications_router)
app.include_router(photos_router)
app.include_router(setup_router)


class LoginInput(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class UserOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str
    role: Role


class BranchOutput(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    location: str


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/ready")
def ready(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ready"}


@app.post("/api/auth/login")
def login(data: LoginInput, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(data.email).lower()))
    valid = password_hash.verify(data.password, user.password_hash if user else dummy_hash)
    if not valid or user is None or not user.is_active:
        raise HTTPException(401, "Invalid email or password")
    return {"access_token": issue_token(user), "token_type": "bearer"}


@app.get("/api/auth/me", response_model=UserOutput)
def me(user: User = Depends(current_user)):
    return user


@app.get("/api/branches", response_model=list[BranchOutput])
def branches(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # All roles are scoped to explicitly granted branches, including administrators.
    return db.scalars(
        select(Branch)
        .join(BranchAccess)
        .where(BranchAccess.user_id == user.id)
        .order_by(Branch.name)
    ).all()
