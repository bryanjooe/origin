"""Account and cookie-session support imported from shezan-branch.

Synchronous routes run password hashing in FastAPI's worker pool.
Existing simulation endpoints retain their contracts and behavior.
"""
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
import sqlite3
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field
from app.schemas.api import Envelope

router = APIRouter()


def runtime(request: Request):
    return request.app.state.runtime


def ok(data):
    return {"data": data}


SESSION_COOKIE = "origin_session"
SESSION_DAYS = 14
PASSWORD_ITERATIONS = 310_000


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def _email(value):
    normalized = value.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", normalized):
        raise HTTPException(422, "Enter a valid email address")
    return normalized


def _password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS).hex()


def _token_hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _issue_session(request, response, user, store):
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    store.create_auth_session(_token_hash(token), user["id"], expires.isoformat())
    response.set_cookie(SESSION_COOKIE, token, max_age=SESSION_DAYS * 24 * 60 * 60,
                        httponly=True, secure=request.url.scheme == "https", samesite="lax", path="/")
    return {"id": user["id"], "email": user["email"], "name": user["name"]}


@router.get("/api/auth/me", response_model=Envelope)
def auth_me(request: Request):
    service = runtime(request)
    token = request.cookies.get(SESSION_COOKIE)
    user = service.store.user_by_session(_token_hash(token), datetime.now(timezone.utc).isoformat()) if token else None
    return ok({"authenticated": user is not None, "user": user})

@router.post("/api/auth/register", response_model=Envelope, status_code=201)
def auth_register(request: Request, response: Response, body: RegisterRequest):
    service = runtime(request)
    email = _email(body.email)
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Name is required")
    salt = secrets.token_bytes(16)
    user = {"id": str(uuid4()), "email": email, "name": name}
    try:
        service.store.create_user(user["id"], email, name, base64.b64encode(salt).decode("ascii"),
                                  _password_hash(body.password, salt))
    except sqlite3.IntegrityError as error:
        if service.store.user_by_email(email):
            raise HTTPException(409, "An account with this email already exists") from error
        raise
    user = _issue_session(request, response, user, service.store)
    return ok({"authenticated": True, "user": user})

@router.post("/api/auth/login", response_model=Envelope)
def auth_login(request: Request, response: Response, body: LoginRequest):
    service = runtime(request)
    email = _email(body.email)
    account = service.store.user_by_email(email)
    if account is None:
        raise HTTPException(401, "Email or password is incorrect")
    salt = base64.b64decode(account["salt"])
    candidate = _password_hash(body.password, salt)
    if not hmac.compare_digest(candidate, account["password_hash"]):
        raise HTTPException(401, "Email or password is incorrect")
    return ok({"authenticated": True, "user": _issue_session(request, response, account, service.store)})

@router.post("/api/auth/logout", response_model=Envelope)
def auth_logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        runtime(request).store.delete_auth_session(_token_hash(token))
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
    return ok({"authenticated": False, "user": None})
