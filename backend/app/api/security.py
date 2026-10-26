"""Lightweight principal authentication, bounded rate limits, and body limits."""
from __future__ import annotations

from collections import defaultdict, deque
import hashlib
import hmac
import re
import threading
import time
from uuid import uuid4

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import JSONResponse

from .errors import APIError


_SUBJECT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$")
MAX_REQUEST_BODY_BYTES = 128 * 1024
_bearer_scheme = HTTPBearer(auto_error=False)


class PrincipalAuthenticator:
    """Authenticate configured opaque bearer tokens without exposing raw token values."""

    def __init__(self, tokens: dict[str, str]):
        self._subjects_by_digest = {
            hashlib.sha256(token.encode("utf-8")).hexdigest(): subject
            for token, subject in tokens.items()
        }

    def authenticate(self, authorization: str | None) -> str:
        if not self._subjects_by_digest:
            raise APIError(503, "authentication_unavailable", "Private API access is not configured.")
        scheme, separator, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not separator or not token or token.strip() != token:
            raise APIError(401, "unauthorized", "Valid bearer authorization is required.")
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        subject = None
        for expected_digest, configured_subject in self._subjects_by_digest.items():
            if hmac.compare_digest(digest, expected_digest):
                subject = configured_subject
        if subject is None:
            raise APIError(401, "unauthorized", "Valid bearer authorization is required.")
        return subject


class PrincipalRateLimiter:
    """Single-process sliding-window limits; bounded keys and request costs."""

    def __init__(self, window_seconds: float = 60.0):
        self.window_seconds = window_seconds
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _policy(method: str, path: str) -> tuple[str, int]:
        if method == "POST" and path.endswith("/analyses"):
            return "analysis", 5
        if method == "POST" and path.endswith("/advance"):
            return "simulation_advance", 30
        if method == "POST" and path == "/api/v1/runs":
            return "run_create", 10
        if method in {"POST", "PATCH"} and "/incidents" in path:
            return "incident_write", 30
        return "general", 120

    def check(self, principal: str, method: str, path: str) -> None:
        bucket, limit = self._policy(method, path)
        now = time.monotonic()
        key = (principal, bucket)
        with self._lock:
            events = self._events[key]
            cutoff = now - self.window_seconds
            while events and events[0] <= cutoff:
                events.popleft()
            if len(events) >= limit:
                raise APIError(429, "rate_limited", "Request rate limit exceeded.")
            events.append(now)
            if not events:
                self._events.pop(key, None)


class RequestTooLarge(Exception):
    pass


class RequestHardeningMiddleware:
    """Enforce an actual received-byte limit and attach one opaque request ID."""

    def __init__(self, app, max_body_bytes: int = MAX_REQUEST_BODY_BYTES):
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        headers = dict(scope.get("headers", []))
        raw_length = headers.get(b"content-length")
        if raw_length is not None:
            try:
                content_length = int(raw_length)
            except ValueError:
                await self._reject(scope, receive, send, request_id, 400, "invalid_content_length", "Content-Length is invalid.")
                return
            if content_length < 0:
                await self._reject(scope, receive, send, request_id, 400, "invalid_content_length", "Content-Length is invalid.")
                return
            if content_length > self.max_body_bytes:
                await self._reject(scope, receive, send, request_id, 413, "request_too_large", "Request body exceeds the configured limit.")
                return

        total = 0

        async def limited_receive():
            nonlocal total
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > self.max_body_bytes:
                    raise RequestTooLarge()
            return message

        async def identified_send(message):
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = response_headers
            await send(message)

        try:
            await self.app(scope, limited_receive, identified_send)
        except RequestTooLarge:
            await self._reject(scope, receive, send, request_id, 413, "request_too_large", "Request body exceeds the configured limit.")

    @staticmethod
    async def _reject(scope, receive, send, request_id, status_code, code, message):
        response = JSONResponse(
            status_code=status_code,
            content={"error": {"code": code, "message": message, "request_id": request_id}},
            headers={"X-Request-ID": request_id},
        )
        await response(scope, receive, send)


def authenticated_principal(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    authorization = (
        f"{credentials.scheme} {credentials.credentials}"
        if credentials is not None else None
    )
    principal = request.app.state.authenticator.authenticate(authorization)
    request.app.state.rate_limiter.check(
        principal, request.method, request.url.path
    )
    return principal
