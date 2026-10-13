"""Authentication utilities and routes for Cal Tracker."""

import sqlite3
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Cookie, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

import database
from config import settings

router = APIRouter()
pwd_context = CryptContext(
    schemes=["argon2", "sha256_crypt"],
    deprecated="sha256_crypt",
)
bearer_scheme = HTTPBearer(auto_error=False)
TOKEN_LIFETIME = timedelta(days=1)


class LoginCredentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class RegistrationCredentials(LoginCredentials):
    password: str = Field(min_length=12, max_length=1024)


def hash_password(password: str) -> str:
    """Hash passwords with Argon2id."""
    return pwd_context.hash(password)


def create_access_token(user_id: int, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or TOKEN_LIFETIME)
    return jwt.encode(
        {"sub": str(user_id), "exp": expire},
        settings.JWT_SECRET,
        algorithm="HS256",
    )


def decode_access_token(token: str) -> int:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=["HS256"])
        return int(payload["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Could not validate credentials") from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    access_token: str | None = Cookie(default=None),
) -> int:
    token = credentials.credentials if credentials else access_token
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    return decode_access_token(token)


def _auth_response(user_id: int, first_time: bool) -> JSONResponse:
    token = create_access_token(user_id)
    response = JSONResponse(
        content={"user_id": user_id, "access_token": token, "first_time": first_time}
    )
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=int(TOKEN_LIFETIME.total_seconds()),
        path="/",
    )
    return response


def _is_unique_violation(exc: Exception) -> bool:
    return isinstance(exc, sqlite3.IntegrityError) or getattr(exc, "sqlstate", None) == "23505"


@router.post("/api/register")
async def register(credentials: RegistrationCredentials) -> JSONResponse:
    username = credentials.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    conn = database.get_db_connection()
    try:
        cursor = database.get_cursor(conn)
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (
            username,
            hash_password(credentials.password),
        ))
        user_id = cursor.lastrowid
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if _is_unique_violation(exc):
            raise HTTPException(status_code=409, detail="Username already taken") from exc
        raise
    finally:
        conn.close()
    return _auth_response(user_id, first_time=True)


@router.post("/api/login")
async def login(credentials: LoginCredentials) -> JSONResponse:
    username = credentials.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    conn = database.get_db_connection()
    try:
        cursor = database.get_cursor(conn)
        cursor.execute(
            "SELECT id, password_hash FROM users WHERE username = ?",
            (username,),
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        valid, replacement_hash = pwd_context.verify_and_update(
            credentials.password,
            row["password_hash"],
        )
        if not valid:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if replacement_hash:
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (replacement_hash, row["id"]),
            )
            conn.commit()
        user_id = row["id"]
    finally:
        conn.close()
    return _auth_response(user_id, first_time=False)
