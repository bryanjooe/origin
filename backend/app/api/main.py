"""FastAPI application factory and ASGI entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import APISettings
from .analysis_service import AIAnalysisService
from .errors import install_exception_handlers
from .incident_service import IncidentService
from .routes import router
from .service import SimulationService
from app.persistence.artifacts import FileArtifactStore
from app.persistence.database import Database
from app.persistence.repository import SQLAlchemyRepository


def create_app(
    settings: APISettings | None = None,
    service: SimulationService | None = None,
    database: Database | None = None,
    artifact_store: FileArtifactStore | None = None,
) -> FastAPI:
    api_settings = settings or APISettings.from_env()

    owns_database = database is None
    api_database = database or Database(api_settings.database_url)
    repository = service.repository if service is not None else SQLAlchemyRepository(api_database.session_factory)
    store = artifact_store or FileArtifactStore(api_settings.data_dir)
    api_service = service or SimulationService(repository, store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            repository.check_ready()
            api_service.restore()
            app.state.persistence_ready = True
        except Exception:
            # Keep liveness available and return an uninformative readiness failure.
            logging.getLogger("tracex.api").error("Persistence is not ready; apply migrations and check the database.")
            app.state.persistence_ready = False
        yield
        if owns_database:
            api_database.dispose()

    app = FastAPI(
        title="TraceX GreenGrid API",
        description="Persistent microgrid simulation API. No AI inference is provided.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.settings = api_settings
    app.state.database = api_database
    app.state.repository = repository
    app.state.service = api_service
    app.state.incident_service = IncidentService(repository)
    app.state.analysis_service = AIAnalysisService(repository)
    app.state.persistence_ready = False

    @app.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request_id = uuid4().hex
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    if api_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(api_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type"],
        )

    install_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()
