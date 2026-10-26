"""Versioned API v1 routes."""
from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from sqlalchemy.exc import SQLAlchemyError

from app.fault_injection import Fault
from app.simulator import GridConfig

from .errors import APIError
from .incident_service import IncidentService
from .security import authenticated_principal
from .schemas import (
    AdvanceInput,
    AdvanceResponse,
    AnalysisJobResponse,
    AnalysisResultResponse,
    AnalysisSubmissionInput,
    ControllerLogsResponse,
    CorrectionResponse,
    DependencyHealthResponse,
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


def get_service(
    request: Request,
    _principal_id: str = Depends(authenticated_principal),
) -> SimulationService:
    if not getattr(request.app.state, "persistence_ready", False):
        raise APIError(503, "not_ready", "API services are not ready.")
    return request.app.state.service


def get_incident_service(
    request: Request,
    _principal_id: str = Depends(authenticated_principal),
) -> IncidentService:
    if not getattr(request.app.state, "persistence_ready", False):
        raise APIError(503, "not_ready", "API services are not ready.")
    return request.app.state.incident_service


def get_analysis_coordinator(
    request: Request,
    _principal_id: str = Depends(authenticated_principal),
):
    if not getattr(request.app.state, "persistence_ready", False):
        raise APIError(503, "not_ready", "API services are not ready.")
    return request.app.state.analysis_coordinator


def _uuid(value: UUID) -> str:
    return str(value)


@router.get("/health/live", response_model=HealthResponse, tags=["health"])
def liveness() -> dict:
    return {"status": "ok"}


@router.get("/health/ready", response_model=HealthResponse, tags=["health"])
def readiness(request: Request) -> dict:
    if not getattr(request.app.state, "persistence_ready", False):
        raise APIError(503, "not_ready", "API services are not ready.")
    try:
        request.app.state.repository.check_ready()
    except SQLAlchemyError:
        raise APIError(503, "not_ready", "Persistent storage is unavailable.") from None
    return {"status": "ready"}


@router.get(
    "/health/dependencies",
    response_model=DependencyHealthResponse,
    tags=["health"],
)
def dependency_health(request: Request) -> dict:
    try:
        request.app.state.repository.check_ready()
    except SQLAlchemyError:
        database_status = "unavailable"
    else:
        database_status = "ready"
    return {
        "api": "ok",
        "database": database_status,
        "ai_service": request.app.state.ai_service_status,
    }


@router.get("/fault-types", response_model=FaultCatalogResponse, tags=["simulation"])
def list_fault_types() -> dict:
    return fault_catalog()


@router.post("/runs", response_model=RunResponse, status_code=201, tags=["runs"])
def create_run(
    payload: RunCreateInput,
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    config = GridConfig(**payload.config.model_dump())
    fault = None
    if payload.fault is not None:
        fault = Fault(**payload.fault.model_dump())
    run = service.create_run(config, payload.seed, fault, owner_id=principal_id)
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
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.status(_uuid(run_id), owner_id=principal_id)


@router.post(
    "/runs/{run_id}/analyses",
    response_model=AnalysisJobResponse,
    status_code=202,
    tags=["analysis"],
)
def submit_analysis(
    run_id: UUID,
    payload: AnalysisSubmissionInput,
    idempotency_key: str = Header(..., alias="Idempotency-Key", min_length=8, max_length=128),
    principal_id: str = Depends(authenticated_principal),
    coordinator=Depends(get_analysis_coordinator),
) -> dict:
    return coordinator.submit_run_analysis(
        run_id=str(run_id),
        start_tick=payload.start_tick,
        end_tick=payload.end_tick,
        idempotency_key=idempotency_key,
        owner_id=principal_id,
    )


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisResultResponse,
    tags=["analysis"],
)
def get_analysis(
    analysis_id: UUID,
    request: Request,
    principal_id: str = Depends(authenticated_principal),
) -> dict:
    if not getattr(request.app.state, "persistence_ready", False):
        raise APIError(503, "not_ready", "API services are not ready.")
    record = request.app.state.analysis_service.get(str(analysis_id), owner_id=principal_id)
    return {
        "analysis_id": record["id"],
        "simulation_run_id": record["simulation_run_id"],
        "incident_id": record["incident_id"],
        "status": record["status"],
        "provider_name": record["provider_name"],
        "model_name": record["model_name"],
        "model_version": record["model_version"],
        "schema_version": record["schema_version"],
        "result": record["validated_output"],
        "failure_code": record["failure_code"],
        "failure_message": record["failure_message"],
        "created_at": record["created_at"],
        "updated_at": record["updated_at"],
        "started_at": record["started_at"],
        "completed_at": record["completed_at"],
    }


@router.post(
    "/runs/{run_id}/advance",
    response_model=AdvanceResponse,
    tags=["runs"],
)
def advance_run(
    run_id: UUID,
    payload: AdvanceInput,
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    if payload.ticks > MAX_ADVANCE_TICKS:
        raise APIError(422, "invalid_tick_count", f"ticks must be at most {MAX_ADVANCE_TICKS}.")
    return service.advance(_uuid(run_id), payload.ticks, owner_id=principal_id)


@router.post(
    "/runs/{run_id}/fault-schedules",
    response_model=FaultScheduleResponse,
    status_code=201,
    tags=["runs"],
)
def schedule_fault(
    run_id: UUID,
    payload: FaultScheduleInput,
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.schedule_fault(_uuid(run_id), Fault(**payload.model_dump()), owner_id=principal_id)


@router.post(
    "/runs/{run_id}/correct",
    response_model=CorrectionResponse,
    tags=["runs"],
)
def correct_run(
    run_id: UUID,
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.correct(_uuid(run_id), owner_id=principal_id)


@router.get(
    "/runs/{run_id}/telemetry",
    response_model=TelemetryResponse,
    tags=["telemetry"],
)
def get_telemetry(
    run_id: UUID,
    start_tick: int = Query(default=0, ge=0),
    end_tick: int | None = Query(default=None, ge=0),
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.telemetry(_uuid(run_id), start_tick, end_tick, owner_id=principal_id)


@router.get(
    "/runs/{run_id}/controller-logs",
    response_model=ControllerLogsResponse,
    tags=["telemetry"],
)
def get_controller_logs(
    run_id: UUID,
    start_tick: int = Query(default=0, ge=0),
    end_tick: int | None = Query(default=None, ge=0),
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.controller_logs(_uuid(run_id), start_tick, end_tick, owner_id=principal_id)


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
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.export_metadata(_uuid(run_id), owner_id=principal_id)


@router.get(
    "/runs/{run_id}/results",
    response_model=ResultMetadataResponse,
    tags=["exports"],
)
def get_result_metadata(
    run_id: UUID,
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> dict:
    return service.result_metadata(_uuid(run_id), owner_id=principal_id)


@router.post(
    "/incidents",
    response_model=IncidentResponse,
    status_code=201,
    tags=["incidents"],
)
def create_incident(
    payload: IncidentCreateInput,
    principal_id: str = Depends(authenticated_principal),
    service: IncidentService = Depends(get_incident_service),
) -> dict:
    return service.create(payload.model_dump(mode="json"), owner_id=principal_id)


@router.get(
    "/incidents",
    response_model=IncidentListResponse,
    tags=["incidents"],
)
def list_incidents(
    page: int = Query(default=1, ge=1, le=10000),
    page_size: int = Query(default=50, ge=1, le=100),
    status: IncidentStatus | None = None,
    category: str | None = Query(default=None, min_length=1, max_length=100),
    affected_component: str | None = Query(default=None, min_length=1, max_length=100),
    simulation_run_id: UUID | None = None,
    principal_id: str = Depends(authenticated_principal),
    service: IncidentService = Depends(get_incident_service),
) -> dict:
    return service.list(
        page=page,
        page_size=page_size,
        status=status,
        category=category,
        affected_component=affected_component,
        simulation_run_id=str(simulation_run_id) if simulation_run_id else None,
        owner_id=principal_id,
    )


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    tags=["incidents"],
)
def get_incident(
    incident_id: UUID,
    principal_id: str = Depends(authenticated_principal),
    service: IncidentService = Depends(get_incident_service),
) -> dict:
    return service.get(str(incident_id), owner_id=principal_id)


@router.patch(
    "/incidents/{incident_id}",
    response_model=IncidentResponse,
    tags=["incidents"],
)
def update_incident(
    incident_id: UUID,
    payload: IncidentUpdateInput,
    principal_id: str = Depends(authenticated_principal),
    service: IncidentService = Depends(get_incident_service),
) -> dict:
    return service.update(str(incident_id), payload.model_dump(exclude_unset=True), owner_id=principal_id)


@router.get(
    "/runs/{run_id}/exports/{format_name}",
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
    principal_id: str = Depends(authenticated_principal),
    service: SimulationService = Depends(get_service),
) -> Response:
    content, media_type = service.export(
        _uuid(run_id), format_name, start_tick, end_tick, owner_id=principal_id
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
