"""Safe, structured API exceptions and handlers."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError


class APIError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


def _error_body(request: Request, code: str, message: str, details: Any = None) -> dict:
    error = {
        "code": code,
        "message": message,
        "request_id": getattr(request.state, "request_id", None),
    }
    if details is not None:
        error["details"] = details
    return {"error": error}


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Deliberately omit the rejected input value; it may contain credentials.
        details = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=_error_body(
                request, "validation_error", "Request validation failed.", details
            ),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
        if isinstance(exc.detail, dict):
            code = str(exc.detail.get("code", "http_error"))
            message = str(exc.detail.get("message", "Request failed."))
        else:
            code, message = "http_error", "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_body(request, code, message),
            headers=exc.headers,
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=_error_body(request, "persistence_conflict", "The requested record conflicts with stored data."),
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logging.getLogger("tracex.api").error(
            "Database operation failed (request_id=%s)",
            getattr(request.state, "request_id", "unknown"),
        )
        return JSONResponse(
            status_code=503,
            content=_error_body(request, "persistence_unavailable", "Persistent storage is unavailable."),
        )

    @app.exception_handler(Exception)
    async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        # Do not log exception text, request bodies, URLs, or credentials.
        logging.getLogger("tracex.api").error(
            "Unhandled API error (request_id=%s, exception_type=%s)",
            request_id,
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content=_error_body(
                request,
                "internal_error",
                "An internal error occurred.",
            ),
        )
