"""Generic HTTP adapter for the separately developed model service."""
from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable
from urllib.parse import urlsplit

import httpx
from pydantic import ValidationError

from .contracts import AnalysisInferenceRequest, ProviderAnalysisResponse


class AnalysisProviderError(Exception):
    code = "provider_error"
    public_message = "The analysis provider could not complete the request."


class ProviderUnavailable(AnalysisProviderError):
    code = "provider_unavailable"
    public_message = "The analysis provider is not configured or is unavailable."


class ProviderTimedOut(AnalysisProviderError):
    code = "provider_timeout"
    public_message = "The analysis provider timed out."


class ProviderRateLimited(AnalysisProviderError):
    code = "provider_rate_limited"
    public_message = "The analysis provider rate limit was reached."


class ProviderInvalidResponse(AnalysisProviderError):
    code = "provider_invalid_response"
    public_message = "The analysis provider returned an invalid response."


class ProviderRequestFailed(AnalysisProviderError):
    code = "provider_request_failed"
    public_message = "The analysis provider rejected or failed the request."


@dataclass(frozen=True)
class HTTPAnalysisProvider:
    """POST to `<base_url>/v1/analyze`; only transient errors receive bounded retries."""

    base_url: str
    api_key: str | None = None
    timeout_seconds: float = 10.0
    max_retries: int = 1
    _client_factory: Callable[..., httpx.Client] = httpx.Client
    _sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("AI service URL must be an absolute HTTP or HTTPS URL")
        if not 0 < self.timeout_seconds <= 120:
            raise ValueError("AI timeout must be greater than 0 and at most 120 seconds")
        if not 0 <= self.max_retries <= 3:
            raise ValueError("AI retries must be between 0 and 3")

    def analyze(self, request: AnalysisInferenceRequest) -> ProviderAnalysisResponse:
        if not self.base_url:
            raise ProviderUnavailable()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url.rstrip('/')}/v1/analyze"
        try:
            with self._client_factory(timeout=self.timeout_seconds) as client:
                for attempt in range(self.max_retries + 1):
                    try:
                        response = client.post(
                            url,
                            json=request.model_dump(mode="json"),
                            headers=headers,
                        )
                    except httpx.TransportError as exc:
                        if attempt < self.max_retries:
                            self._sleep(min(0.1 * (2 ** attempt), 1.0))
                            continue
                        if isinstance(exc, httpx.TimeoutException):
                            raise ProviderTimedOut() from exc
                        raise ProviderUnavailable() from exc

                    if response.status_code in {408, 429} or response.status_code >= 500:
                        if attempt < self.max_retries:
                            self._sleep(min(0.1 * (2 ** attempt), 1.0))
                            continue
                        if response.status_code == 429:
                            raise ProviderRateLimited()
                        if response.status_code == 408:
                            raise ProviderTimedOut()
                        raise ProviderUnavailable()
                    if response.is_error:
                        raise ProviderRequestFailed()
                    try:
                        return ProviderAnalysisResponse.model_validate(response.json())
                    except (ValueError, ValidationError) as exc:
                        raise ProviderInvalidResponse() from exc
        except AnalysisProviderError:
            raise
        except httpx.TransportError as exc:
            raise ProviderUnavailable() from exc
        raise ProviderUnavailable()


@dataclass(frozen=True)
class UnavailableAnalysisProvider:
    """Default adapter until the AI team provides a reachable service or local model."""

    def analyze(self, request: AnalysisInferenceRequest) -> ProviderAnalysisResponse:
        raise ProviderUnavailable()
