"""Incident business rules over the persistence repository."""
from __future__ import annotations

from app.persistence.repository import SQLAlchemyRepository
from app.propagation import build_topology

from .errors import APIError


class IncidentService:
    def __init__(self, repository: SQLAlchemyRepository):
        self.repository = repository
        self._components = frozenset(build_topology().nodes)

    def create(self, values: dict) -> dict:
        self._validate_component(values["affected_component"])
        incident = self.repository.create_incident(values)
        if incident is None:
            raise APIError(404, "run_not_found", "Simulation run was not found.")
        return incident

    def list(
        self,
        *,
        page: int,
        page_size: int,
        status: str | None,
        category: str | None,
        affected_component: str | None,
        simulation_run_id: str | None,
    ) -> dict:
        if affected_component is not None:
            self._validate_component(affected_component)
        items, total = self.repository.list_incidents(
            page=page,
            page_size=page_size,
            status=status,
            category=category,
            affected_component=affected_component,
            simulation_run_id=simulation_run_id,
        )
        return {"items": items, "page": page, "page_size": page_size, "total": total}

    def get(self, incident_id: str) -> dict:
        incident = self.repository.get_incident(incident_id)
        if incident is None:
            raise APIError(404, "incident_not_found", "Incident was not found.")
        return incident

    def update(self, incident_id: str, changes: dict) -> dict:
        if "affected_component" in changes:
            self._validate_component(changes["affected_component"])
        incident = self.repository.update_incident(incident_id, changes)
        if incident is None:
            raise APIError(404, "incident_not_found", "Incident was not found.")
        return incident

    def _validate_component(self, component: str) -> None:
        if component not in self._components:
            raise APIError(
                422,
                "invalid_component",
                "affected_component must name a component in the dependency topology.",
            )
