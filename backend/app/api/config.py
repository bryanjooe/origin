"""Environment-backed settings for the HTTP API."""
from dataclasses import dataclass
from dataclasses import field
import json
import os
from pathlib import Path
import re
from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class APISettings:
    environment: str = "development"
    cors_origins: tuple[str, ...] = ()
    api_tokens: dict[str, str] = field(default_factory=dict, repr=False)
    database_url: str = field(
        default="postgresql+psycopg://localhost:5432/tracex_greengrid", repr=False
    )
    data_dir: str = "data"
    ai_service_url: str | None = None
    ai_service_api_key: str | None = field(default=None, repr=False)
    ai_timeout_seconds: float = 10.0
    ai_max_retries: int = 1
    ai_workers: int = 2
    ai_queue_size: int = 8

    def __post_init__(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("TRACEX_ENV must be development, test, or production")
        if self.environment == "production" and any(origin.strip() == "*" for origin in self.cors_origins):
            raise ValueError("Wildcard CORS origins are not allowed in production")
        try:
            database = make_url(self.database_url)
        except Exception as exc:
            raise ValueError("TRACEX_DATABASE_URL is invalid") from exc
        if not database.drivername.startswith("sqlite") and not database.drivername.startswith("postgresql"):
            raise ValueError("Only PostgreSQL and SQLite database URLs are supported")
        if self.environment == "production" and not database.drivername.startswith("postgresql"):
            raise ValueError("Production requires PostgreSQL")
        if self.environment == "production" and not self.api_tokens:
            raise ValueError("Production requires at least one configured API token")
        if not isinstance(self.api_tokens, dict):
            raise ValueError("TRACEX_API_TOKENS must be a JSON object")
        for token, subject in self.api_tokens.items():
            if not isinstance(token, str) or not token or (self.environment == "production" and len(token) < 32):
                raise ValueError("Production API tokens must contain at least 32 characters")
            if not isinstance(subject, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}", subject):
                raise ValueError("API token subjects must be stable identifier strings")
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
        raw_tokens = os.getenv("TRACEX_API_TOKENS", "{}")
        try:
            api_tokens = json.loads(raw_tokens)
        except json.JSONDecodeError as exc:
            raise ValueError("TRACEX_API_TOKENS must be a JSON object") from exc
        if not isinstance(api_tokens, dict):
            raise ValueError("TRACEX_API_TOKENS must be a JSON object")
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
            api_tokens=api_tokens,
            database_url=database_url,
            data_dir=data_dir,
            ai_service_url=ai_service_url,
            ai_service_api_key=ai_service_api_key,
            ai_timeout_seconds=float(os.getenv("TRACEX_AI_TIMEOUT_SECONDS", "10")),
            ai_max_retries=int(os.getenv("TRACEX_AI_MAX_RETRIES", "1")),
            ai_workers=int(os.getenv("TRACEX_AI_WORKERS", "2")),
            ai_queue_size=int(os.getenv("TRACEX_AI_QUEUE_SIZE", "8")),
        )
