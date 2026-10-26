"""FastAPI application factory and ASGI entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.contracts import AnalysisProvider
from app.ai.jobs import AnalysisJobCoordinator
from app.ai.provider import HTTPAnalysisProvider, UnavailableAnalysisProvider
from .config import APISettings
from .analysis_service import AIAnalysisService
from .errors import install_exception_handlers
from .incident_service import IncidentService
from .routes import router
from .security import PrincipalAuthenticator, PrincipalRateLimiter, RequestHardeningMiddleware
from .service import SimulationService
from app.persistence.artifacts import FileArtifactStore
from app.persistence.database import Database
from app.persistence.repository import SQLAlchemyRepository


def create_app(
    settings: APISettings | None = None,
    service: SimulationService | None = None,
    database: Database | None = None,
    artifact_store: FileArtifactStore | None = None,
    analysis_provider: AnalysisProvider | None = None,
) -> FastAPI:
    api_settings = settings or APISettings.from_env()

    owns_database = database is None
    api_database = database or Database(api_settings.database_url)
    repository = service.repository if service is not None else SQLAlchemyRepository(api_database.session_factory)
    store = artifact_store or FileArtifactStore(api_settings.data_dir)
    api_service = service or SimulationService(repository, store)
    analysis_service = AIAnalysisService(repository)
    provider = analysis_provider or (
        HTTPAnalysisProvider(
            base_url=api_settings.ai_service_url,
            api_key=api_settings.ai_service_api_key,
            timeout_seconds=api_settings.ai_timeout_seconds,
            max_retries=api_settings.ai_max_retries,
        )
        if api_settings.ai_service_url
        else UnavailableAnalysisProvider()
    )
    analysis_coordinator = AnalysisJobCoordinator(
        simulation_service=api_service,
        analysis_service=analysis_service,
        provider=provider,
        max_workers=api_settings.ai_workers,
        max_queue=api_settings.ai_queue_size,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            repository.check_ready()
            repository.fail_interrupted_analyses()
            api_service.restore()
            app.state.persistence_ready = True
        except Exception:
            # Keep liveness available and return an uninformative readiness failure.
            logging.getLogger("tracex.api").error("Persistence is not ready; apply migrations and check the database.")
            app.state.persistence_ready = False
        yield
        try:
            analysis_coordinator.shutdown()
        finally:
            if owns_database:
                api_database.dispose()

    app = FastAPI(
        title="TraceX GreenGrid API",
        description=(
            "Persistent microgrid simulation API with a provider-independent AI adapter. "
            "Real inference is available only when the separately developed provider is configured."
        ),
        version="1.0.0",
        lifespan=lifespan,
        debug=False,
    )
    app.state.settings = api_settings
    app.state.database = api_database
    app.state.repository = repository
    app.state.service = api_service
    app.state.incident_service = IncidentService(repository)
    app.state.analysis_service = analysis_service
    app.state.analysis_coordinator = analysis_coordinator
    app.state.ai_service_status = (
        "not_configured"
        if isinstance(provider, UnavailableAnalysisProvider)
        else "configured_unverified"
    )
    app.state.authenticator = PrincipalAuthenticator(api_settings.api_tokens)
    app.state.rate_limiter = PrincipalRateLimiter()
    app.state.persistence_ready = False

    if api_settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(api_settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        )

    app.add_middleware(RequestHardeningMiddleware)

    install_exception_handlers(app)
    app.include_router(router)
    return app


app = create_app()
