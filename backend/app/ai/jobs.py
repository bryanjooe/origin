"""Bounded in-process job orchestration around a pluggable analysis provider."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import hashlib
import json
import logging
import threading

from pydantic import ValidationError

from app.api.analysis_service import AIAnalysisService
from app.api.errors import APIError
from app.api.service import SimulationService

from .contracts import AnalysisInferenceRequest, AnalysisProvider, ProviderAnalysisResponse
from .provider import AnalysisProviderError, ProviderInvalidResponse


logger = logging.getLogger("tracex.ai")


class AnalysisJobCoordinator:
    def __init__(
        self,
        *,
        simulation_service: SimulationService,
        analysis_service: AIAnalysisService,
        provider: AnalysisProvider,
        max_workers: int = 2,
        max_queue: int = 8,
    ) -> None:
        self.simulation_service = simulation_service
        self.analysis_service = analysis_service
        self.provider = provider
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="tracex-analysis"
        )
        self._capacity = threading.BoundedSemaphore(max_workers + max_queue)
        self._lock = threading.RLock()
        self._futures: dict[str, Future] = {}
        self._closed = False

    def submit_run_analysis(
        self,
        *,
        run_id: str,
        start_tick: int,
        end_tick: int | None,
        idempotency_key: str,
    ) -> dict:
        # The snapshot is a strict telemetry/controller-log allowlist and is captured
        # before the job is queued, so later advances cannot enter its input.
        snapshot = self.simulation_service.analysis_snapshot(run_id, start_tick, end_tick)
        request_template = AnalysisInferenceRequest(
            analysis_id="pending",
            simulation_run_id=run_id,
            window=snapshot["window"],
            telemetry=snapshot["telemetry"],
            controller_logs=snapshot["controller_logs"],
        )
        fingerprint_source = {
            "simulation_run_id": run_id,
            "requested_start_tick": start_tick,
            "requested_end_tick": end_tick,
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_source, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        analysis_id, created = self.analysis_service.create_pending_idempotent(
            simulation_run_id=run_id,
            idempotency_key=idempotency_key,
            input_sha256=fingerprint,
        )
        if created:
            request = request_template.model_copy(update={"analysis_id": analysis_id})
            with self._lock:
                if self._closed:
                    self.analysis_service.fail(
                        analysis_id, "worker_unavailable", "Analysis worker is shutting down."
                    )
                elif not self._capacity.acquire(blocking=False):
                    self.analysis_service.fail(
                        analysis_id, "worker_capacity", "Analysis worker capacity is full."
                    )
                else:
                    try:
                        future = self._executor.submit(self._run, analysis_id, request)
                    except RuntimeError:
                        self._capacity.release()
                        self.analysis_service.fail(
                            analysis_id, "worker_unavailable", "Analysis worker is unavailable."
                        )
                    else:
                        self._futures[analysis_id] = future
                        future.add_done_callback(lambda _future, key=analysis_id: self._finished(key))
        record = self.analysis_service.get(analysis_id)
        return {
            "analysis_id": analysis_id,
            "status": record["status"],
            "status_path": f"/api/v1/analyses/{analysis_id}",
        }

    def _run(self, analysis_id: str, request: AnalysisInferenceRequest) -> None:
        try:
            self.analysis_service.mark_running(
                analysis_id, provider_name=type(self.provider).__name__
            )
            try:
                response = ProviderAnalysisResponse.model_validate(self.provider.analyze(request))
            except ValidationError as exc:
                raise ProviderInvalidResponse() from exc
            self.analysis_service.complete(
                analysis_id,
                response.result,
                provider_name=type(self.provider).__name__,
                model_name=response.model_name,
                model_version=response.model_version,
            )
        except AnalysisProviderError as exc:
            self.analysis_service.fail(analysis_id, exc.code, exc.public_message)
        except Exception:
            # Do not log adapter exception text or payloads; they may contain secrets.
            logger.error("Analysis adapter failed unexpectedly (analysis_id=%s)", analysis_id)
            try:
                self.analysis_service.fail(
                    analysis_id,
                    "analysis_failed",
                    "Analysis could not be completed because of an internal integration error.",
                )
            except Exception:
                logger.error("Could not persist failed analysis state (analysis_id=%s)", analysis_id)

    def _finished(self, analysis_id: str) -> None:
        with self._lock:
            self._futures.pop(analysis_id, None)
            self._capacity.release()

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=False)
