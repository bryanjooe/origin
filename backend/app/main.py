"""Local FastAPI application. Launch with one Uvicorn worker."""
import asyncio
from contextlib import asynccontextmanager
import csv
import io
import json
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.config import ServerSettings
from app.api.runtime import RuntimeConflict, SimulationRuntime
from app.propagation import build_topology
from app.schemas.api import (Envelope, ErrorEnvelope, EvaluateRequest, FaultRequest, ResetRequest,
                             ScenarioRequest, SpeedRequest, StartRequest, StepRequest)


def create_app(settings: ServerSettings | None = None):
    @asynccontextmanager
    async def lifespan(application):
        runtime = await asyncio.to_thread(SimulationRuntime, settings or ServerSettings.from_environment())
        application.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="TraceX GreenGrid", version="0.5.0", lifespan=lifespan,
                  description="Software-only microgrid simulation, diagnosis and durable incident history.",
                  responses={422: {"model": ErrorEnvelope}, 409: {"model": ErrorEnvelope},
                             404: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope}})
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

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

    @app.get("/api/model/metrics", response_model=Envelope)
    async def model_metrics(request: Request):
        service = runtime(request)
        async with service.lock:
            return ok({"models": service.models.availability(), "artifact_sha256": service.models.fingerprints,
                       "datasets": {name: {"training_rows": model.metadata["training_rows"],
                                            "training_runs": len(model.metadata["training_runs"]),
                                            **({"calibration_rows": model.metadata["calibration_rows"],
                                                "calibration_runs": len(model.metadata["calibration_runs"])} if name == "anomaly" else {})}
                                    for name, model in (("anomaly", service.models.detector), ("source", service.models.localizer)) if model is not None},
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
        headers = {"Content-Disposition": f'attachment; filename="tracex-{dataset}.{format}"',
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
