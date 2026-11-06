import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import User

password_hash = PasswordHash.recommended()
dummy_hash = password_hash.hash("invalid-account-timing-placeholder")
bearer = HTTPBearer(auto_error=False)


def issue_token(user: User) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id),
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    error = HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    if credentials is None:
        raise error
    try:
        payload = jwt.decode(
            credentials.credentials,
            get_settings().jwt_secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat"]},
        )
        user = db.get(User, uuid.UUID(payload["sub"]))
    except (InvalidTokenError, ValueError, TypeError):
        raise error from None
    if user is None or not user.is_active:
        raise error
    return user
