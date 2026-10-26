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

    def __post_init__(self) -> None:
        if self.environment.strip().lower() == "production" and "*" in self.cors_origins:
            raise ValueError("Wildcard CORS origins are not allowed in production")

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
        return cls(environment, origins, key or None, incident_key or None, database_url, data_dir)
