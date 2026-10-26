"""Local FastAPI application. Launch with one Uvicorn worker."""
import asyncio
import base64
from contextlib import asynccontextmanager
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import io
import json
import re
import secrets
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel, Field

from app.api.config import ServerSettings
from app.api.runtime import RuntimeConflict, SimulationRuntime
from app.propagation import build_topology
from app.propagation.investigation import evidence_graph
from app.schemas.api import (AttackRequest, Envelope, ErrorEnvelope, EvaluateRequest, FaultRequest, ResetRequest,
                             ScenarioRequest, SpeedRequest, StartRequest, StepRequest)

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


def create_app(settings: ServerSettings | None = None):
    @asynccontextmanager
    async def lifespan(application):
        runtime = await asyncio.to_thread(SimulationRuntime, settings or ServerSettings.from_environment())
        application.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="Origin", version="0.5.0", lifespan=lifespan,
                  description="Software-only microgrid simulation, diagnosis and durable incident history.",
                  responses={422: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope},
                             404: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope}})
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://127.0.0.1:5175", "http://127.0.0.1:5176"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=True)

    def runtime(request: Request):
        return request.app.state.runtime

    def ok(data):
        return {"data": data}

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        details = [{"location": list(item["loc"]), "message": item["msg"], "type": item["type"]} for item in error.errors()]
        return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Invalid request", "details": details}})

    @app.exception_handler(RuntimeConflict)
    async def conflict(request, error):
        return JSONResponse(status_code=409, content={"error": {"code": "state_conflict", "message": str(error), "details": []}})

    @app.exception_handler(ValueError)
    async def invalid_value(request, error):
        return JSONResponse(status_code=422, content={"error": {"code": "invalid_operation", "message": str(error), "details": []}})

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        return JSONResponse(status_code=error.status_code, content={"error": {"code": f"http_{error.status_code}", "message": str(error.detail), "details": []}})

    @app.exception_handler(Exception)
    async def internal_error(request, error):
        return JSONResponse(status_code=500, content={"error": {"code": "internal_error", "message": "Backend operation failed; inspect server logs", "details": []}})

    @app.get("/api/auth/me", response_model=Envelope)
    async def auth_me(request: Request):
        service = runtime(request)
        token = request.cookies.get(SESSION_COOKIE)
        user = service.store.user_by_session(_token_hash(token), datetime.now(timezone.utc).isoformat()) if token else None
        return ok({"authenticated": user is not None, "user": user})

    @app.post("/api/auth/register", response_model=Envelope, status_code=201)
    async def auth_register(request: Request, response: Response, body: RegisterRequest):
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
        except Exception as error:
            if service.store.user_by_email(email):
                raise HTTPException(409, "An account with this email already exists") from error
            raise
        user = _issue_session(request, response, user, service.store)
        return ok({"authenticated": True, "user": user})

    @app.post("/api/auth/login", response_model=Envelope)
    async def auth_login(request: Request, response: Response, body: LoginRequest):
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

    @app.post("/api/auth/logout", response_model=Envelope)
    async def auth_logout(request: Request, response: Response):
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            runtime(request).store.delete_auth_session(_token_hash(token))
        response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="lax")
        return ok({"authenticated": False, "user": None})

    @app.get("/api/health", response_model=Envelope)
    async def health(request: Request):
        service = runtime(request)
        async with service.lock:
            availability = service.models.availability()
            return ok({"status": "ok" if all(item["available"] for item in availability.values()) and not service.error else "degraded",
                       "database": "available", "models": availability, "runtime_error": service.error,
                       "transport": "REST polling", "suggested_poll_interval_ms": 1000})

    @app.get("/api/system/state", response_model=Envelope)
    async def state(request: Request):
        service = runtime(request)
        async with service.lock:
            return ok(service.state())

    @app.get("/api/system/topology", response_model=Envelope)
    async def topology():
        graph = build_topology()
        return ok({"nodes": [{"id": node, **data} for node, data in graph.nodes(data=True)],
                   "edges": [{"source": a, "target": b, **data} for a, b, data in graph.edges(data=True)]})

    @app.post("/api/simulation/start", response_model=Envelope)
    @app.post("/api/simulation/resume", response_model=Envelope)
    async def start(request: Request, body: StartRequest | None = None):
        return ok(await runtime(request).start(body.speed if body else None))

    @app.post("/api/simulation/pause", response_model=Envelope)
    async def pause(request: Request):
        return ok(await runtime(request).pause())

    @app.post("/api/simulation/speed", response_model=Envelope)
    async def speed(request: Request, body: SpeedRequest):
        return ok(await runtime(request).set_speed(body.speed))

    @app.post("/api/simulation/step", response_model=Envelope)
    async def step(request: Request, body: StepRequest):
        return ok(await runtime(request).step(body.ticks))

    @app.post("/api/simulation/reset", response_model=Envelope)
    async def reset(request: Request, body: ResetRequest | None = None):
        return ok(await runtime(request).reset(body.seed if body else None))

    @app.post("/api/simulation/scenario", response_model=Envelope)
    async def scenario(request: Request, body: ScenarioRequest):
        return ok(await runtime(request).reset(seed=body.seed, config=body.config.grid_config(),
                                               fault=body.fault.fault(0) if body.fault else None))

    @app.get("/api/simulation/scenario", response_model=Envelope)
    async def current_scenario(request: Request):
        service = runtime(request)
        async with service.lock:
            service.store.update_scenario(service.run_id, "running" if service.running else "paused", service.metadata())
            return ok(service.store.scenario(service.run_id))

    @app.get("/api/scenarios", response_model=Envelope)
    async def scenarios(request: Request, limit: int = Query(100, ge=1, le=1000)):
        service = runtime(request)
        async with service.lock:
            return ok(service.store.scenarios(limit))

    @app.post("/api/simulation/inject-fault", response_model=Envelope)
    async def inject(request: Request, body: FaultRequest):
        return ok(await runtime(request).inject(body))

    @app.post("/api/simulation/inject-attack", response_model=Envelope)
    async def inject_attack(request: Request, body: AttackRequest):
        return ok(await runtime(request).inject_attack(body))

    @app.post("/api/simulation/correct", response_model=Envelope)
    async def correct(request: Request):
        return ok(await runtime(request).correct())

    @app.get("/api/telemetry", response_model=Envelope)
    async def telemetry(request: Request, run_id: str | None = None, after_tick: int = Query(-1, ge=-1),
                        limit: int = Query(300, ge=1, le=2000)):
        service = runtime(request)
        async with service.lock:
            selected = run_id or service.run_id
            if not service.store.scenario(selected):
                raise HTTPException(404, "Scenario not found")
            items = service.store.telemetry(selected, after_tick, limit)
            return ok({"run_id": selected, "items": items,
                       "next_after_tick": items[-1]["telemetry"]["tick"] if items else after_tick})

    @app.get("/api/events", response_model=Envelope)
    async def events(request: Request, run_id: str | None = None, after_id: int = Query(0, ge=0),
                     limit: int = Query(100, ge=1, le=2000)):
        service = runtime(request)
        async with service.lock:
            items = service.store.events(run_id, after_id, limit)
            return ok({"items": items, "next_after_id": items[-1]["id"] if items else after_id})

    @app.get("/api/incidents", response_model=Envelope)
    async def incidents(request: Request, run_id: str | None = None,
                        severity: Literal["warning", "critical"] | None = None,
                        status: Literal["open", "resolved", "interrupted"] | None = None,
                        source: Literal["sensor", "communication", "controller", "firmware", "inverter", "unknown"] | None = None,
                        search: str = Query("", max_length=100), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        service = runtime(request)
        async with service.lock:
            return ok(service.store.incidents(run_id=run_id, severity=severity, status=status, source=source,
                                               search=search, limit=limit, offset=offset))

    @app.get("/api/incidents/{incident_id}", response_model=Envelope)
    async def incident(request: Request, incident_id: str):
        service = runtime(request)
        async with service.lock:
            report = service.store.incident(incident_id)
            if report is None:
                raise HTTPException(404, "Incident not found")
            if report.get("security_attribution") is None:
                assessment = service.security_attribution(report)
                if assessment.get("status") == "pending" and report["status"] != "open":
                    assessment.update(status="insufficient_evidence", reason="Historical incident has insufficient observed telemetry for a complete window.")
                report["security_attribution"] = assessment
                service.store.save_security_assessment(incident_id, assessment)
            report["graph"] = evidence_graph(report["graph"], report["security_attribution"], report.get("evidence", []))
            return ok(report)

    @app.get("/api/incidents/{incident_id}/graph", response_model=Envelope)
    async def graph(request: Request, incident_id: str):
        result = await incident(request, incident_id)
        return ok(result["data"]["graph"])

    @app.get("/api/metrics/sustainability", response_model=Envelope)
    async def sustainability(request: Request):
        service = runtime(request)
        async with service.lock:
            return ok({"run_id": service.run_id, **service.sustainability()})

    @app.get("/api/security/metrics", response_model=Envelope)
    async def security_metrics(request: Request):
        service = runtime(request)
        async with service.lock:
            return ok(service.models.security_metrics())

    @app.get("/api/model/metrics", response_model=Envelope)
    async def model_metrics(request: Request):
        service = runtime(request)
        async with service.lock:
            return ok({"models": service.models.availability(), "artifact_sha256": service.models.fingerprints,
                       "training_scenarios": {
                           "anomaly": len(service.models.detector.metadata.get("training_runs", [])) if service.models.detector else None,
                           "anomaly_calibration": len(service.models.detector.metadata.get("calibration_runs", [])) if service.models.detector else None,
                           "source": len(service.models.localizer.metadata.get("training_runs", [])) if service.models.localizer else None,
                       },
                       "evaluation": dict(service.evaluation), "reports": deepcopy_reports(service.models.reports),
                       "saved_report_errors": dict(service.models.report_errors)})

    @app.post("/api/model/evaluate", response_model=Envelope, status_code=202)
    async def evaluate(request: Request, body: EvaluateRequest | None = None):
        try:
            return ok(await runtime(request).start_evaluation(body.profile if body else "full"))
        except LookupError as error:
            raise HTTPException(503, str(error)) from error

    @app.get("/api/reports/export")
    async def export(request: Request, dataset: Literal["incidents", "telemetry", "scenario"] = "incidents",
                     format: Literal["json", "csv"] = "json", run_id: str | None = None,
                     limit: int = Query(5000, ge=1, le=10000)):
        service = runtime(request)
        async with service.lock:
            selected = run_id or service.run_id
            if dataset != "incidents" and not service.store.scenario(selected):
                raise HTTPException(404, "Scenario not found")
            if dataset == "incidents":
                listing = service.store.incidents(run_id=run_id, limit=limit)
                data = [service.store.incident(item["id"]) for item in listing["items"]]
                truncated = listing["total"] > len(data)
            elif dataset == "telemetry":
                items = service.store.telemetry(selected, -1, limit + 1)
                data = items[:limit]
                truncated = len(items) > limit
            else:
                data = [service.store.scenario(selected)]
                truncated = False
        headers = {"Content-Disposition": f'attachment; filename="origin-{dataset}.{format}"',
                   "X-Export-Truncated": str(truncated).lower()}
        if format == "json":
            return JSONResponse(content=jsonable_encoder({"data": data, "truncated": truncated}), headers=headers)
        stream = io.StringIO(newline="")
        if data:
            writer = csv.DictWriter(stream, fieldnames=list(dict.fromkeys(key for item in data for key in item)))
            writer.writeheader()
            for item in data:
                writer.writerow({key: json.dumps(value) if isinstance(value, (dict, list)) else value for key, value in item.items()})
        return Response(content=stream.getvalue(), media_type="text/csv", headers=headers)

    return app


def deepcopy_reports(value):
    # Reports contain JSON data only; do not expose mutable model registry state.
    return json.loads(json.dumps(value))


app = create_app()
