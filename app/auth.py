"""
auth.py
-------
Password hashing (passlib/bcrypt), JWT issue + verify (pyjwt), and the FastAPI
dependencies that guard the mutating endpoints.

    get_current_user  -> requires a valid Bearer token, returns the user doc
    require_admin      -> as above, plus role == "admin"
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext

from .config import JWT_ALGORITHM, JWT_EXPIRE_MINUTES, JWT_SECRET
from .db import users

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=True)
_bearer_optional = HTTPBearer(auto_error=False)


def hash_password(plain: str) -> str:
    return _pwd.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _pwd.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(username: str, role: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": username,
        "role": role,
        "iat": now,
        "exp": now + dt.timedelta(minutes=JWT_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")


def authenticate(username: str, password: str) -> dict[str, Any] | None:
    user = users().find_one({"username": username})
    if not user or not verify_password(password, user.get("password_hash", "")):
        return None
    return user


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict[str, Any]:
    claims = _decode(creds.credentials)
    user = users().find_one({"username": claims.get("sub")})
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    return user


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin role required")
    return user


def get_optional_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_optional),
) -> dict[str, Any] | None:
    """Like get_current_user, but never raises: returns None with no/bad token.
    For endpoints that stay open (e.g. /ingest/*) but should still attribute the
    action to a real operator when the caller happens to be logged in."""
    if not creds:
        return None
    try:
        claims = _decode(creds.credentials)
    except HTTPException:
        return None
    return users().find_one({"username": claims.get("sub")})
