"""Persistence lifecycle for real AI analysis results; performs no inference."""
from __future__ import annotations

from uuid import uuid4

from app.persistence.repository import AnalysisIdempotencyConflict, SQLAlchemyRepository

from .errors import APIError
from .schemas import AIAnalysisOutput


class AIAnalysisService:
    def __init__(self, repository: SQLAlchemyRepository):
        self.repository = repository

    def create_pending(
        self,
        *,
        simulation_run_id: str | None = None,
        incident_id: str | None = None,
        owner_id: str | None = None,
    ) -> str:
        if simulation_run_id is None and incident_id is None:
            raise APIError(422, "analysis_context_required", "An analysis must reference a run or incident.")
        analysis_id = str(uuid4())
        self.repository.create_analysis(
            analysis_id=analysis_id,
            owner_id=owner_id,
            run_id=simulation_run_id,
            incident_id=incident_id,
            status="pending",
            model_name=None,
            model_version=None,
            schema_version="1",
            validated_output=None,
        )
        return analysis_id

    def create_pending_idempotent(
        self,
        *,
        simulation_run_id: str | None = None,
        incident_id: str | None = None,
        owner_id: str | None = None,
        idempotency_key: str,
        input_sha256: str,
    ) -> tuple[str, bool]:
        if simulation_run_id is None and incident_id is None:
            raise APIError(422, "analysis_context_required", "An analysis must reference a run or incident.")
        analysis_id = str(uuid4())
        try:
            return self.repository.create_analysis(
                analysis_id=analysis_id,
                owner_id=owner_id,
                run_id=simulation_run_id,
                incident_id=incident_id,
                status="pending",
                model_name=None,
                model_version=None,
                schema_version="1",
                validated_output=None,
                idempotency_key=idempotency_key,
                input_sha256=input_sha256,
            )
        except AnalysisIdempotencyConflict as exc:
            raise APIError(
                409,
                "idempotency_key_reused",
                "This Idempotency-Key was already used for different analysis input.",
            ) from exc

    def mark_running(
        self,
        analysis_id: str,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> None:
        self._update(analysis_id, {
            "status": "running",
            "provider_name": provider_name,
            "model_name": model_name,
            "model_version": model_version,
            "validated_output": None,
            "failure_code": None,
            "failure_message": None,
        })

    def complete(
        self,
        analysis_id: str,
        output: AIAnalysisOutput | dict,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> None:
        validated = AIAnalysisOutput.model_validate(output)
        self._update(analysis_id, {
            "status": "completed",
            "provider_name": provider_name,
            "model_name": model_name,
            "model_version": model_version,
            "schema_version": validated.schema_version,
            "validated_output": validated.model_dump(mode="json"),
            "failure_code": None,
            "failure_message": None,
        })

    def fail(self, analysis_id: str, code: str, message: str) -> None:
        self._update(analysis_id, {
            "status": "failed",
            "failure_code": code[:80],
            "failure_message": message[:500],
            "validated_output": None,
        })

    def get(self, analysis_id: str, *, owner_id: str | None = None) -> dict:
        result = self.repository.get_analysis(analysis_id, owner_id=owner_id)
        if result is None:
            raise APIError(404, "analysis_not_found", "Analysis record was not found.")
        return result

    def _update(self, analysis_id: str, changes: dict) -> None:
        if not self.repository.update_analysis(analysis_id, changes):
            raise APIError(404, "analysis_not_found", "Analysis record was not found.")
