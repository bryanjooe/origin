"""Environment-backed settings for the HTTP API."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class APISettings:
    environment: str = "development"
    cors_origins: tuple[str, ...] = ()
    export_api_key: str | None = None
    incident_api_key: str | None = None
    database_url: str = "postgresql+psycopg://localhost:5432/tracex_greengrid"
    data_dir: str = "data"
    ai_service_url: str | None = None
    ai_service_api_key: str | None = None
    ai_timeout_seconds: float = 10.0
    ai_max_retries: int = 1
    ai_workers: int = 2
    ai_queue_size: int = 8

    def __post_init__(self) -> None:
        if self.environment.strip().lower() == "production" and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins are not allowed in production")
        if self.ai_timeout_seconds <= 0 or self.ai_timeout_seconds > 120:
            raise ValueError("AI timeout must be greater than 0 and at most 120 seconds")
        if not 0 <= self.ai_max_retries <= 3:
            raise ValueError("AI retries must be between 0 and 3")
        if self.ai_workers < 1 or self.ai_workers > 8:
            raise ValueError("AI workers must be between 1 and 8")
        if self.ai_queue_size < 0 or self.ai_queue_size > 64:
            raise ValueError("AI queue size must be between 0 and 64")

    @classmethod
    def from_env(cls) -> "APISettings":
        environment = os.getenv("TRACEX_ENV", "development").strip().lower()
        origins = tuple(
            origin.strip()
            for origin in os.getenv("TRACEX_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        key = os.getenv("TRACEX_EXPORT_API_KEY")
        incident_key = os.getenv("TRACEX_INCIDENT_API_KEY")
        database_url = os.getenv(
            "TRACEX_DATABASE_URL",
            "postgresql+psycopg://localhost:5432/tracex_greengrid",
        )
        data_dir = os.getenv("TRACEX_DATA_DIR", str(Path("data")))
        ai_service_url = os.getenv("TRACEX_AI_SERVICE_URL", "").strip() or None
        ai_service_api_key = os.getenv("TRACEX_AI_SERVICE_API_KEY") or None
        return cls(
            environment=environment,
            cors_origins=origins,
            export_api_key=key or None,
            incident_api_key=incident_key or None,
            database_url=database_url,
            data_dir=data_dir,
            ai_service_url=ai_service_url,
            ai_service_api_key=ai_service_api_key,
            ai_timeout_seconds=float(os.getenv("TRACEX_AI_TIMEOUT_SECONDS", "10")),
            ai_max_retries=int(os.getenv("TRACEX_AI_MAX_RETRIES", "1")),
            ai_workers=int(os.getenv("TRACEX_AI_WORKERS", "2")),
            ai_queue_size=int(os.getenv("TRACEX_AI_QUEUE_SIZE", "8")),
        )
