"""Repeatable API and persistence smoke check; creates one retained simulation run."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from .api.config import APISettings
from .api.main import create_app


def run_smoke(settings: APISettings | None = None) -> dict[str, object]:
    settings = settings or APISettings.from_env()
    if not settings.api_tokens:
        raise RuntimeError("Configure at least one TRACEX_API_TOKENS entry before the smoke test.")
    token = next(iter(settings.api_tokens))
    headers = {"Authorization": f"Bearer {token}"}

    with TestClient(create_app(settings=settings), headers=headers) as client:
        if client.get("/api/v1/health/live").status_code != 200:
            raise RuntimeError("API liveness check failed.")
        if client.get("/api/v1/health/ready").status_code != 200:
            raise RuntimeError("Database readiness check failed.")

        created = client.post("/api/v1/runs", json={"seed": 8128})
        if created.status_code != 201:
            raise RuntimeError("Simulation run creation failed.")
        run_id = created.json()["run_id"]

        advanced = client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 3})
        if advanced.status_code != 200 or advanced.json().get("current_tick") != 3:
            raise RuntimeError("Simulation advancement failed.")
        status = client.get(f"/api/v1/runs/{run_id}")
        telemetry = client.get(f"/api/v1/runs/{run_id}/telemetry")
        results = client.get(f"/api/v1/runs/{run_id}/results")
        if status.status_code != 200 or status.json().get("current_tick") != 3:
            raise RuntimeError("Run status retrieval failed.")
        if telemetry.status_code != 200 or len(telemetry.json().get("rows", [])) != 3:
            raise RuntimeError("Telemetry retrieval failed.")
        if results.status_code != 200:
            raise RuntimeError("Result metadata retrieval failed.")

    # A new app instance and database pool verify persisted state after restart.
    with TestClient(create_app(settings=settings), headers=headers) as client:
        status = client.get(f"/api/v1/runs/{run_id}")
        telemetry = client.get(f"/api/v1/runs/{run_id}/telemetry")
        results = client.get(f"/api/v1/runs/{run_id}/results")
        if status.status_code != 200 or status.json().get("current_tick") != 3:
            raise RuntimeError("Run did not persist across application restart.")
        if telemetry.status_code != 200 or len(telemetry.json().get("rows", [])) != 3:
            raise RuntimeError("Telemetry did not persist across application restart.")
        if results.status_code != 200:
            raise RuntimeError("Result metadata did not persist across application restart.")

    return {
        "status": "passed",
        "run_id": run_id,
        "ticks_persisted": 3,
        "restarted_app_verified": True,
    }


def main() -> None:
    result = run_smoke()
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
