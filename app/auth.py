"""Authentication utilities and routes for Cal Tracker."""

import hashlib
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import jwt
from authlib.integrations.base_client.errors import OAuthError
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from passlib.context import CryptContext
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse, RedirectResponse

from . import database
from .config import settings

router = APIRouter()
logger = logging.getLogger(__name__)
pwd_context = CryptContext(
    schemes=["argon2", "sha256_crypt"],
    deprecated="sha256_crypt",
)
bearer_scheme = HTTPBearer(auto_error=False)
TOKEN_LIFETIME = timedelta(days=1)
oauth = OAuth()
if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


class LoginCredentials(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=1024)


class RegistrationCredentials(LoginCredentials):
    password: str = Field(min_length=12, max_length=1024)


class AccountProfilePayload(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    first_name: str = Field(default="", max_length=100)
    nickname: str = Field(default="", max_length=40)


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
    _set_access_cookie(response, token)
    return response


def _set_access_cookie(response: RedirectResponse | JSONResponse, token: str) -> None:
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=int(TOKEN_LIFETIME.total_seconds()),
        path="/",
    )


def _get_or_create_google_user(subject: str, email: str) -> int:
    conn = database.get_db_connection()
    try:
        cursor = database.get_cursor(conn)
        cursor.execute("SELECT id FROM users WHERE google_sub = ?", (subject,))
        row = cursor.fetchone()
        if row:
            cursor.execute(
                "UPDATE users SET email = ? WHERE id = ?",
                (email, row["id"]),
            )
            conn.commit()
            return row["id"]

        username = f"google_{hashlib.sha256(subject.encode()).hexdigest()[:32]}"
        cursor.execute(
            "INSERT INTO users (username, password_hash, google_sub, email) "
            "VALUES (?, ?, ?, ?)",
            (username, hash_password(secrets.token_urlsafe(48)), subject, email),
        )
        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except Exception as exc:
        conn.rollback()
        if _is_unique_violation(exc):
            cursor = database.get_cursor(conn)
            cursor.execute("SELECT id FROM users WHERE google_sub = ?", (subject,))
            row = cursor.fetchone()
            if row:
                return row["id"]
        raise
    finally:
        conn.close()


@router.get("/api/auth/google/status")
async def google_auth_status() -> dict[str, bool]:
    return {
        "enabled": bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    }


@router.get("/auth/google")
async def google_login(request: Request):
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    redirect_uri = settings.GOOGLE_REDIRECT_URI or str(
        request.url_for("google_callback")
    )
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback", name="google_callback")
async def google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as exc:
        logger.info("Google OAuth authorization was not completed: %s", exc.error)
        return RedirectResponse("/?auth_error=google", status_code=303)

    user_info = token.get("userinfo")
    if not user_info:
        raise HTTPException(status_code=401, detail="Google did not return user information")
    subject = user_info.get("sub")
    email = user_info.get("email")
    if (
        not isinstance(subject, str)
        or not subject
        or not isinstance(email, str)
        or not email
        or user_info.get("email_verified") is not True
    ):
        raise HTTPException(
            status_code=403,
            detail="A verified Google email address is required",
        )

    user_id = _get_or_create_google_user(subject, email)
    response = RedirectResponse("/", status_code=303)
    _set_access_cookie(response, create_access_token(user_id))
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


@router.get("/api/account-profile")
async def get_account_profile(user_id: int = Depends(get_current_user)) -> dict[str, object]:
    account = database.get_user_account(user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return {"account": account}


@router.put("/api/account-profile")
async def update_account_profile(
    data: AccountProfilePayload,
    user_id: int = Depends(get_current_user),
) -> dict[str, object]:
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username is required")

    try:
        account = database.update_user_account(
            user_id=user_id,
            username=username,
            first_name=data.first_name.strip(),
            nickname=data.nickname.strip(),
        )
    except Exception as exc:
        if _is_unique_violation(exc):
            raise HTTPException(status_code=409, detail="Username already taken") from exc
        if isinstance(exc, LookupError):
            raise HTTPException(status_code=404, detail="Account not found") from exc
        raise
    return {"status": "ok", "account": account}
