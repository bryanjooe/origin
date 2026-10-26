"""Versioned API v1 routes."""
from __future__ import annotations

import hmac
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response

from app.fault_injection import Fault
from app.simulator import GridConfig

from .config import APISettings
from .errors import APIError
from .incident_service import IncidentService
from .schemas import (
    AdvanceInput,
    AdvanceResponse,
    ControllerLogsResponse,
    CorrectionResponse,
    DownstreamResponse,
    ExportListResponse,
    FaultCatalogResponse,
    FaultScheduleInput,
    FaultScheduleResponse,
    HealthResponse,
    IncidentCreateInput,
    IncidentListResponse,
    IncidentResponse,
    IncidentStatus,
    IncidentUpdateInput,
    RunCreateInput,
    RunResponse,
    RunStatusResponse,
    ResultMetadataResponse,
    TelemetryResponse,
    TopologyResponse,
)
from .service import (
    MAX_ADVANCE_TICKS,
    MAX_RUN_TICKS,
    SimulationService,
    downstream_data,
    fault_catalog,
    topology_data,
    utc_iso,
)


router = APIRouter(prefix="/api/v1")


def get_service(request: Request) -> SimulationService:
    if not getattr(request.app.state, "persistence_ready", False):
        raise APIError(503, "not_ready", "API services are not ready.")
    return request.app.state.service


def get_settings(request: Request) -> APISettings:
    return request.app.state.settings


def get_incident_service(request: Request) -> IncidentService:
    if not getattr(request.app.state, "persistence_ready", False):
        raise APIError(503, "not_ready", "API services are not ready.")
    return request.app.state.incident_service


def _uuid(value: UUID) -> str:
    return str(value)


@router.get("/health/live", response_model=HealthResponse, tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@router.get("/health/ready", response_model=HealthResponse, tags=["health"])
def readiness(request: Request) -> dict:
    if not getattr(request.app.state, "persistence_ready", False):
        raise APIError(503, "not_ready", "API services are not ready.")
    return {"status": "ready"}


@router.get("/fault-types", response_model=FaultCatalogResponse, tags=["simulation"])
def list_fault_types() -> dict:
    return fault_catalog()


@router.post("/runs", response_model=RunResponse, status_code=201, tags=["runs"])
def create_run(
    payload: RunCreateInput,
    service: SimulationService = Depends(get_service),
) -> dict:
    config = GridConfig(**payload.config.model_dump())
    fault = None
    if payload.fault is not None:
        fault = Fault(**payload.fault.model_dump())
    run = service.create_run(config, payload.seed, fault)
    with run.lock:
        return {
            "run_id": run.run_id,
            "status": run.status,
            "seed": run.simulator.seed,
            "current_tick": run.simulator.tick,
            "max_ticks": MAX_RUN_TICKS,
            "tick_seconds": run.simulator.config.tick_seconds,
            "created_at": utc_iso(run.created_at),
            "updated_at": utc_iso(run.updated_at),
            "error": None,
        }


@router.get("/runs/{run_id}", response_model=RunStatusResponse, tags=["runs"])
def get_run_status(
    run_id: UUID,
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.status(_uuid(run_id))


@router.post(
    "/runs/{run_id}/advance",
    response_model=AdvanceResponse,
    tags=["runs"],
)
def advance_run(
    run_id: UUID,
    payload: AdvanceInput,
    service: SimulationService = Depends(get_service),
) -> dict:
    if payload.ticks > MAX_ADVANCE_TICKS:
        raise APIError(422, "invalid_tick_count", f"ticks must be at most {MAX_ADVANCE_TICKS}.")
    return service.advance(_uuid(run_id), payload.ticks)


@router.post(
    "/runs/{run_id}/fault-schedules",
    response_model=FaultScheduleResponse,
    status_code=201,
    tags=["runs"],
)
def schedule_fault(
    run_id: UUID,
    payload: FaultScheduleInput,
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.schedule_fault(_uuid(run_id), Fault(**payload.model_dump()))


@router.post(
    "/runs/{run_id}/correct",
    response_model=CorrectionResponse,
    tags=["runs"],
)
def correct_run(
    run_id: UUID,
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.correct(_uuid(run_id))


@router.get(
    "/runs/{run_id}/telemetry",
    response_model=TelemetryResponse,
    tags=["telemetry"],
)
def get_telemetry(
    run_id: UUID,
    start_tick: int = Query(default=0, ge=0),
    end_tick: int | None = Query(default=None, ge=0),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.telemetry(_uuid(run_id), start_tick, end_tick)


@router.get(
    "/runs/{run_id}/controller-logs",
    response_model=ControllerLogsResponse,
    tags=["telemetry"],
)
def get_controller_logs(
    run_id: UUID,
    start_tick: int = Query(default=0, ge=0),
    end_tick: int | None = Query(default=None, ge=0),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.controller_logs(_uuid(run_id), start_tick, end_tick)


@router.get("/topology", response_model=TopologyResponse, tags=["topology"])
def get_topology() -> dict:
    return topology_data()


@router.get(
    "/topology/{component}/downstream",
    response_model=DownstreamResponse,
    tags=["topology"],
)
def get_downstream(component: str) -> dict:
    return downstream_data(component)


@router.get(
    "/runs/{run_id}/exports",
    response_model=ExportListResponse,
    tags=["exports"],
)
def get_export_metadata(
    run_id: UUID,
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.export_metadata(_uuid(run_id))


@router.get(
    "/runs/{run_id}/results",
    response_model=ResultMetadataResponse,
    tags=["exports"],
)
def get_result_metadata(
    run_id: UUID,
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.result_metadata(_uuid(run_id))


def authorize_export(
    authorization: str | None = Header(default=None),
    settings: APISettings = Depends(get_settings),
) -> None:
    expected = settings.export_api_key
    if expected is None:
        raise APIError(
            503,
            "export_authorization_unavailable",
            "Export downloads are not configured on this server.",
        )
    scheme, _, supplied = (authorization or "").partition(" ")
    if (
        scheme.lower() != "bearer"
        or not supplied
        or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
    ):
        raise APIError(401, "unauthorized", "Valid bearer authorization is required.")


def authorize_incidents(
    authorization: str | None = Header(default=None),
    settings: APISettings = Depends(get_settings),
) -> None:
    expected = settings.incident_api_key
    if expected is None:
        raise APIError(
            503,
            "incident_authorization_unavailable",
            "Incident access is not configured on this server.",
        )
    scheme, _, supplied = (authorization or "").partition(" ")
    if (
        scheme.lower() != "bearer"
        or not supplied
        or not hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))
    ):
        raise APIError(401, "unauthorized", "Valid bearer authorization is required.")


@router.post(
    "/incidents",
    response_model=IncidentResponse,
    status_code=201,
    dependencies=[Depends(authorize_incidents)],
    tags=["incidents"],
)
def create_incident(
    payload: IncidentCreateInput,
    service: IncidentService = Depends(get_incident_service),
) -> dict:
    return service.create(payload.model_dump(mode="json"))


@router.get(
    "/incidents",
    response_model=IncidentListResponse,
    dependencies=[Depends(authorize_incidents)],
    tags=["incidents"],
)
def list_incidents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    status: IncidentStatus | None = None,
    category: str | None = Query(default=None, min_length=1, max_length=100),
    affected_component: str | None = Query(default=None, min_length=1, max_length=100),
    simulation_run_id: UUID | None = None,
    service: IncidentService = Depends(get_incident_service),
) -> dict:
    return service.list(
        page=page,
        page_size=page_size,
        status=status,
        category=category,
        affected_component=affected_component,
        simulation_run_id=str(simulation_run_id) if simulation_run_id else None,
    )


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    dependencies=[Depends(authorize_incidents)],
    tags=["incidents"],
)
def get_incident(
    incident_id: UUID,
    service: IncidentService = Depends(get_incident_service),
) -> dict:
    return service.get(str(incident_id))


@router.patch(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    dependencies=[Depends(authorize_incidents)],
    tags=["incidents"],
)
def update_incident(
    incident_id: UUID,
    payload: IncidentUpdateInput,
    service: IncidentService = Depends(get_incident_service),
) -> dict:
    return service.update(str(incident_id), payload.model_dump(exclude_unset=True))


@router.get(
    "/runs/{run_id}/exports/{format_name}",
    dependencies=[Depends(authorize_export)],
    responses={
        200: {"content": {"application/json": {}, "text/csv": {}}},
        401: {"description": "Authorization required."},
    },
    tags=["exports"],
)
def download_export(
    run_id: UUID,
    format_name: Literal["csv", "json"],
    start_tick: int = Query(default=0, ge=0),
    end_tick: int | None = Query(default=None, ge=0),
    service: SimulationService = Depends(get_service),
) -> Response:
    content, media_type = service.export(
        _uuid(run_id), format_name, start_tick, end_tick
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="telemetry-{_uuid(run_id)}.{format_name}"'
            )
        },
    )
