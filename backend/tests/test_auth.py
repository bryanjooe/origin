"""Account integration must leave the simulator and existing APIs unchanged."""
from datetime import datetime, timedelta, timezone
import hashlib

from fastapi.testclient import TestClient
import pytest

from app.api.auth import SESSION_COOKIE
from app.api.config import ServerSettings
from app.main import create_app


@pytest.fixture
def client(workspace_tmp_path):
    settings = ServerSettings(database_path=workspace_tmp_path / "auth.sqlite3", anomaly_model=None, source_model=None)
    with TestClient(create_app(settings)) as connection:
        yield connection


ACCOUNT = {"name": " Demo User ", "email": "Demo@example.test", "password": "test-password-123"}


def register(client):
    response = client.post("/api/auth/register", json=ACCOUNT)
    assert response.status_code == 201, response.text
    return response


def test_registration_session_and_existing_simulation(client):
    before = client.get("/api/system/state").json()
    assert client.get("/api/auth/me").json()["data"] == {"authenticated": False, "user": None}
    response = register(client)
    public = response.json()["data"]["user"]
    assert public["name"] == "Demo User" and public["email"] == "demo@example.test"
    assert set(public) == {"id", "email", "name"}
    assert "HttpOnly" in response.headers["set-cookie"] and "SameSite=lax" in response.headers["set-cookie"]
    assert client.get("/api/auth/me").json()["data"]["user"] == public
    assert client.get("/api/system/state").json() == before
    stored = client.app.state.runtime.store.user_by_email(ACCOUNT["email"])
    assert stored["password_hash"] != ACCOUNT["password"] and len(stored["password_hash"]) == 64
    session = client.app.state.runtime.store.connection.execute("SELECT token_hash FROM auth_sessions").fetchone()
    assert session["token_hash"] == hashlib.sha256(client.cookies[SESSION_COOKIE].encode()).hexdigest()


def test_logout_revokes_cookie_and_login_restores_account(client):
    original = register(client).json()["data"]["user"]
    token = client.cookies[SESSION_COOKIE]
    assert client.post("/api/auth/logout").status_code == 200
    assert not client.get("/api/auth/me").json()["data"]["authenticated"]
    assert not client.app.state.runtime.store.user_by_session(hashlib.sha256(token.encode()).hexdigest(), datetime.now(timezone.utc).isoformat())
    response = client.post("/api/auth/login", json={"email": "DEMO@example.test", "password": ACCOUNT["password"]})
    assert response.status_code == 200
    assert response.json()["data"]["user"] == original


def test_duplicate_email_and_wrong_password(client):
    register(client)
    assert client.post("/api/auth/register", json={**ACCOUNT, "email": "demo@EXAMPLE.test"}).status_code == 409
    client.post("/api/auth/logout")
    for email in [ACCOUNT["email"], "missing@example.test"]:
        response = client.post("/api/auth/login", json={"email": email, "password": "incorrect"})
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Email or password is incorrect"
    assert not client.get("/api/auth/me").json()["data"]["authenticated"]


@pytest.mark.parametrize("change", [{"email": "invalid"}, {"name": "   "}, {"password": "short"}])
def test_invalid_registration(client, change):
    assert client.post("/api/auth/register", json={**ACCOUNT, **change}).status_code == 422
    assert not client.get("/api/auth/me").json()["data"]["authenticated"]


def test_expired_or_unknown_session_is_anonymous(client):
    register(client)
    store = client.app.state.runtime.store
    with store.lock, store.connection:
        store.connection.execute("UPDATE auth_sessions SET expires_at=?", ((datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),))
    assert not client.get("/api/auth/me").json()["data"]["authenticated"]
    client.cookies.set(SESSION_COOKIE, "unknown-token")
    assert not client.get("/api/auth/me").json()["data"]["authenticated"]


def test_accounts_and_sessions_persist_across_backend_restart(workspace_tmp_path):
    settings = ServerSettings(database_path=workspace_tmp_path / "persistent-auth.sqlite3", anomaly_model=None, source_model=None)
    with TestClient(create_app(settings)) as first:
        user = register(first).json()["data"]["user"]
        token = first.cookies[SESSION_COOKIE]
    with TestClient(create_app(settings)) as second:
        second.cookies.set(SESSION_COOKIE, token)
        assert second.get("/api/auth/me").json()["data"]["user"] == user


def test_allowed_frontend_origin_supports_credentials(client):
    response = client.options("/api/auth/login", headers={"Origin": "http://127.0.0.1:5173", "Access-Control-Request-Method": "POST"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
