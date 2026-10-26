from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
import threading
import tempfile
import time
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.config import APISettings
from app.api.main import create_app
from app.api.service import SimulationService
from app.persistence.artifacts import FileArtifactStore
from app.persistence.database import Database
from app.persistence.models import Base
from app.persistence.repository import SQLAlchemyRepository

TEST_TOKEN = "test-user-token-0123456789abcdef0123456789abcdef"


class ManagedTestClient(TestClient):
    def __init__(self, app, database, temp_directory, *, raise_server_exceptions=True):
        super().__init__(app, raise_server_exceptions=raise_server_exceptions,
                         headers={"Authorization": f"Bearer {TEST_TOKEN}"})
        self._database = database
        self._temp_directory = temp_directory

    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self._database.dispose()
            self._temp_directory.cleanup()


def make_client(
    *, export_api_key=TEST_TOKEN, incident_api_key="incident-secret", origins=(), api_tokens=None,
    raise_server_exceptions=True, analysis_provider=None,
):
    temp_directory = tempfile.TemporaryDirectory(prefix="tracex-api-test-")
    root = Path(temp_directory.name)
    database = Database(f"sqlite+pysqlite:///{(root / 'api.sqlite').as_posix()}")
    Base.metadata.create_all(database.engine)
    repository = SQLAlchemyRepository(database.session_factory)
    artifact_store = FileArtifactStore(root / "artifacts")
    service = SimulationService(repository, artifact_store)
    tokens = api_tokens if api_tokens is not None else {
        token: "test-user" for token in (
            *((TEST_TOKEN,) if export_api_key is not None or incident_api_key is not None else ()),
            export_api_key,
            incident_api_key,
        ) if token
    }
    app = create_app(
        settings=APISettings(
            cors_origins=tuple(origins),
            api_tokens=tokens,
            database_url="sqlite+pysqlite:///:memory:",
            data_dir=str(root / "artifacts"),
        ),
        service=service,
        database=database,
        artifact_store=artifact_store,
        analysis_provider=analysis_provider,
    )
    return ManagedTestClient(
        app, database, temp_directory,
        raise_server_exceptions=raise_server_exceptions,
    )


def create_run(client, **body):
    response = client.post("/api/v1/runs", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_health_fault_catalog_and_cors_settings():
    with make_client(origins=("http://localhost:3000",)) as client:
        assert client.get("/api/v1/health/live").json() == {"status": "ok"}
        assert client.get("/api/v1/health/ready").json() == {"status": "ready"}
        catalog = client.get("/api/v1/fault-types").json()
        families = {family["name"]: {mode["name"] for mode in family["modes"]}
                    for family in catalog["fault_types"]}
        assert families["sensor"] == {"bias", "drift", "noise", "soc_bias", "stuck"}
        assert families["inverter"] == {"delay", "derate", "efficiency", "shutdown"}
        assert catalog["parameters"]["severity_min_exclusive"] == 0
        preflight = client.options(
            "/api/v1/runs",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert preflight.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_run_advance_status_telemetry_controller_logs_and_truth_separation():
    with make_client() as client:
        run = create_run(
            client,
            seed=17,
            config={"start_hour": 17.0},
            fault={
                "kind": "inverter",
                "mode": "derate",
                "severity": 0.8,
                "duration_ticks": 3,
                "start_tick": 1,
            },
        )
        assert run["current_tick"] == 0
        assert "fault" not in run and "ground_truth" not in run
        advanced = client.post(f"/api/v1/runs/{run['run_id']}/advance", json={"ticks": 5})
        assert advanced.status_code == 200
        assert advanced.json()["current_tick"] == 5
        status = client.get(f"/api/v1/runs/{run['run_id']}")
        assert status.status_code == 200
        assert status.json()["current_tick"] == 5
        telemetry = client.get(
            f"/api/v1/runs/{run['run_id']}/telemetry",
            params={"start_tick": 1, "end_tick": 4},
        )
        assert telemetry.status_code == 200
        assert [row["tick"] for row in telemetry.json()["rows"]] == [1, 2, 3]
        assert all("fault" not in row and "severity" not in row for row in telemetry.json()["rows"])
        logs = client.get(f"/api/v1/runs/{run['run_id']}/controller-logs")
        assert logs.status_code == 200
        assert [row["tick"] for row in logs.json()["logs"]] == list(range(5))
        assert "controller_command_kw" in logs.json()["logs"][0]
        assert "scenario_ground_truth" not in telemetry.text


def test_fault_validation_config_constraints_and_tick_ranges():
    with make_client() as client:
        invalid_bodies = [
            {"fault": {"kind": "unknown", "mode": "bias"}},
            {"fault": {"kind": "sensor", "mode": "shutdown"}},
            {"fault": {"kind": "sensor", "mode": "bias", "severity": 0}},
            {"fault": {"kind": "sensor", "mode": "bias", "severity": 1.01}},
            {"fault": {"kind": "sensor", "mode": "bias", "duration_ticks": 0}},
            {"config": {"tick_seconds": 0}},
            {"config": {"initial_soc_pct": 40, "reserve_soc_pct": 60}},
            {"config": {"communication_delay_ticks": 1.5}},
            {"config": {"unexpected_setting": 1}},
        ]
        for body in invalid_bodies:
            response = client.post("/api/v1/runs", json=body)
            assert response.status_code == 422, (body, response.text)
            assert response.json()["error"]["code"] == "validation_error"
            assert all("input" not in detail for detail in response.json()["error"]["details"])

        run = create_run(client)
        run_id = run["run_id"]
        assert client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 1001}).status_code == 422
        assert client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 0}).status_code == 422
        assert client.get(f"/api/v1/runs/{run_id}/telemetry", params={"start_tick": 1}).status_code == 422
        assert client.get(
            f"/api/v1/runs/{run_id}/telemetry",
            params={"start_tick": 4, "end_tick": 3},
        ).status_code == 422
        assert client.post(
            f"/api/v1/runs/{run_id}/fault-schedules",
            json={"kind": "inverter", "mode": "shutdown", "start_tick": -1},
        ).status_code == 422


def test_missing_resources_and_structured_errors():
    with make_client() as client:
        missing = str(uuid4())
        response = client.get(f"/api/v1/runs/{missing}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "run_not_found"
        assert "traceback" not in response.text.lower()
        unknown_component = client.get("/api/v1/topology/not-a-component/downstream")
        assert unknown_component.status_code == 404
        assert unknown_component.json()["error"]["code"] == "component_not_found"
        assert client.get("/api/v1/topology/solar/downstream").json()["downstream"]
        assert client.get("/api/v1/topology").json()["edges"]
        assert client.get("/api/v1/runs/not-a-uuid").status_code == 422


def test_fault_scheduling_conflict_correction_and_no_truth_route():
    with make_client() as client:
        run_id = create_run(client)["run_id"]
        first = client.post(
            f"/api/v1/runs/{run_id}/fault-schedules",
            json={"kind": "sensor", "mode": "bias", "start_tick": 2, "duration_ticks": 3},
        )
        assert first.status_code == 201
        overlap = client.post(
            f"/api/v1/runs/{run_id}/fault-schedules",
            json={"kind": "inverter", "mode": "derate", "start_tick": 4, "duration_ticks": 1},
        )
        assert overlap.status_code == 409
        assert overlap.json()["error"]["code"] == "fault_schedule_conflict"
        client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 4})
        past = client.post(
            f"/api/v1/runs/{run_id}/fault-schedules",
            json={"kind": "controller", "mode": "wrong_dispatch", "start_tick": 3},
        )
        assert past.status_code == 422
        correction = client.post(f"/api/v1/runs/{run_id}/correct")
        assert correction.status_code == 200
        assert correction.json()["current_tick"] == 4
        assert client.get(f"/api/v1/runs/{run_id}/scenario-ground-truth").status_code == 404


def test_authorized_exports_metadata_and_no_credentials_or_truth():
    with make_client(export_api_key="long-secret-value") as client:
        run_id = create_run(client)["run_id"]
        client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 3})
        metadata = client.get(f"/api/v1/runs/{run_id}/exports")
        assert metadata.status_code == 200
        details = metadata.json()
        assert details["max_export_ticks"] == 10_000
        assert {entry["format"] for entry in details["exports"]} == {"csv", "json"}
        assert all(entry["authorization_required"] for entry in details["exports"])
        assert "long-secret-value" not in metadata.text
        assert "ground_truth" not in metadata.text

        denied = client.get(f"/api/v1/runs/{run_id}/exports/json", headers={"Authorization": "Bearer invalid"})
        assert denied.status_code == 401
        assert denied.json()["error"]["code"] == "unauthorized"
        invalid = client.get(
            f"/api/v1/runs/{run_id}/exports/csv",
            headers={"Authorization": "Bearer wrong"},
        )
        assert invalid.status_code == 401
        for format_name in ("json", "csv"):
            response = client.get(
                f"/api/v1/runs/{run_id}/exports/{format_name}",
                headers={"Authorization": "Bearer long-secret-value"},
            )
            assert response.status_code == 200
            assert response.headers["content-disposition"].endswith(f".{format_name}\"")
            assert "ground_truth" not in response.text
            assert "severity" not in response.text
        assert json.loads(client.get(
            f"/api/v1/runs/{run_id}/exports/json",
            headers={"Authorization": "Bearer long-secret-value"},
        ).text)[0]["tick"] == 0


def test_private_api_unavailable_without_configured_principals():
    with make_client(export_api_key=None, incident_api_key=None) as client:
        response = client.get("/api/v1/incidents")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "authentication_unavailable"


def test_private_resources_are_isolated_by_authenticated_principal():
    bob_token = "bob-user-token-0123456789abcdef0123456789abcdef"
    with make_client(api_tokens={TEST_TOKEN: "alice", bob_token: "bob"}) as client:
        run_id = create_run(client)["run_id"]
        incident = client.post("/api/v1/incidents", json={
            "title": "Alice incident", "affected_component": "battery", "category": "observation",
            "simulation_run_id": run_id,
        }).json()
        assert client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 1}).status_code == 200
        analysis_response = client.post(
            f"/api/v1/runs/{run_id}/analyses",
            headers={"Idempotency-Key": "alice-analysis-key-001"},
            json={"start_tick": 0, "end_tick": 1},
        )
        assert analysis_response.status_code == 202, analysis_response.text
        bob = {"Authorization": f"Bearer {bob_token}"}
        assert client.get(f"/api/v1/runs/{run_id}", headers=bob).status_code == 404
        assert client.get(f"/api/v1/runs/{run_id}/telemetry", headers=bob).status_code == 404
        assert client.get(f"/api/v1/runs/{run_id}/results", headers=bob).status_code == 404
        assert client.get(f"/api/v1/runs/{run_id}/exports/json", headers=bob).status_code == 404
        assert client.get(f"/api/v1/incidents/{incident['id']}", headers=bob).status_code == 404
        assert client.get(f"/api/v1/analyses/{analysis_response.json()['analysis_id']}",
                          headers=bob).status_code == 404
        assert client.get("/api/v1/incidents", headers=bob).json()["total"] == 0
        assert client.patch(f"/api/v1/incidents/{incident['id']}", headers=bob,
                            json={"title": "hijack"}).status_code == 404


def test_auth_body_limit_and_live_readiness_failures():
    with make_client() as client:
        unauthenticated = client.get("/api/v1/incidents", headers={"Authorization": "Bearer wrong"})
        assert unauthenticated.status_code == 401
        assert client.get("/api/v1/health/live").status_code == 200
        too_large = client.post("/api/v1/incidents", content=b" " * (128 * 1024 + 1),
                                headers={"Content-Type": "application/json"})
        assert too_large.status_code == 413
        assert too_large.json()["error"]["code"] == "request_too_large"
        repository = client.app.state.repository
        original = repository.check_ready

        def disconnected():
            from sqlalchemy.exc import OperationalError
            raise OperationalError("SELECT 1", {}, RuntimeError("private database detail"))

        repository.check_ready = disconnected
        response = client.get("/api/v1/health/ready")
        assert response.status_code == 503
        assert "private database detail" not in response.text
        repository.check_ready = original


def test_private_rate_limit_returns_structured_429():
    with make_client() as client:
        limiter = client.app.state.rate_limiter
        for _ in range(120):
            limiter.check("test-user", "GET", "/api/v1/incidents")
        response = client.get("/api/v1/incidents")
        assert response.status_code == 429
        assert response.json()["error"]["code"] == "rate_limited"


def test_download_size_limit_is_enforced(monkeypatch):
    from app.api import service as service_module

    monkeypatch.setattr(service_module, "MAX_EXPORT_BYTES", 1)
    with make_client() as client:
        run_id = create_run(client)["run_id"]
        response = client.get(f"/api/v1/runs/{run_id}/exports/json")
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "export_too_large"


def test_incident_crud_filters_pagination_and_ground_truth_rejection():
    headers = {"Authorization": "Bearer incident-secret"}
    with make_client() as client:
        first = client.post(
            "/api/v1/incidents",
            headers=headers,
            json={
                "title": "Voltage observation",
                "affected_component": "solar_sensor",
                "category": "operator_report",
                "description": "Observed by the operator.",
                "observed_evidence": {"tick": 4, "measured_solar_kw": 7.2},
                "priority": "P1",
            },
        )
        assert first.status_code == 201, first.text
        incident = first.json()
        assert incident["investigation_status"] == "open"
        assert incident["category"] == "operator_report"
        assert incident["priority"] == "P1"
        assert "fault" not in first.text and "ground_truth" not in first.text

        second = client.post(
            "/api/v1/incidents",
            headers=headers,
            json={
                "title": "Battery review",
                "affected_component": "battery",
                "category": "maintenance_note",
                "observed_evidence": {"battery_soc_pct": 52.1},
            },
        )
        assert second.status_code == 201
        page = client.get(
            "/api/v1/incidents",
            headers=headers,
            params={"category": "operator_report", "page": 1, "page_size": 1},
        )
        assert page.status_code == 200
        assert page.json()["total"] == 1
        assert len(page.json()["items"]) == 1

        updated = client.patch(
            f"/api/v1/incidents/{incident['id']}",
            headers=headers,
            json={"investigation_status": "investigating", "priority": "P2"},
        )
        assert updated.status_code == 200
        assert updated.json()["investigation_status"] == "investigating"
        assert updated.json()["priority"] == "P2"
        assert client.get(f"/api/v1/incidents/{incident['id']}", headers=headers).json()["id"] == incident["id"]

        forbidden_evidence = client.post(
            "/api/v1/incidents",
            headers=headers,
            json={
                "title": "bad evidence",
                "affected_component": "solar",
                "category": "operator_report",
                "observed_evidence": {"nested": {"scenario_ground_truth": {"mode": "derate"}}},
            },
        )
        assert forbidden_evidence.status_code == 422
        assert client.post(
            "/api/v1/incidents",
            headers=headers,
            json={"title": "unknown", "affected_component": "not-a-component", "category": "note"},
        ).status_code == 422
        assert client.get("/api/v1/incidents", params={"page_size": 101}, headers=headers).status_code == 422
        missing = client.get(f"/api/v1/incidents/{uuid4()}", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "incident_not_found"


def test_incident_api_requires_configured_authorization():
    with make_client(export_api_key=None, incident_api_key=None) as client:
        response = client.get("/api/v1/incidents")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "authentication_unavailable"


def test_concurrent_advance_requests_serialize_same_simulator():
    with make_client() as client:
        service = client.app.state.service
        run_id = create_run(client)["run_id"]
        run = service._get_run(run_id)
        original_step = run.simulator.step
        guard = threading.Lock()
        active = 0
        max_active = 0

        def tracked_step():
            nonlocal active, max_active
            with guard:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.001)
            try:
                return original_step()
            finally:
                with guard:
                    active -= 1

        run.simulator.step = tracked_step

        def advance():
            return client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 10})

        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(lambda _: advance(), range(4)))
        assert all(response.status_code == 200 for response in responses)
        assert max_active == 1
        status = client.get(f"/api/v1/runs/{run_id}").json()
        assert status["current_tick"] == 40
        telemetry = client.get(f"/api/v1/runs/{run_id}/telemetry").json()["rows"]
        assert [row["tick"] for row in telemetry] == list(range(40))


def test_internal_failures_are_logged_but_sanitized(caplog):
    with make_client(raise_server_exceptions=False) as client:
        service = client.app.state.service
        run_id = create_run(client)["run_id"]

        def fail(*_args, **_kwargs):
            raise RuntimeError("secret path C:\\private\\scenario_ground_truth.json")

        service.advance = fail
        with caplog.at_level(logging.ERROR, logger="tracex.api"):
            response = client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 1})
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "internal_error"
        assert "RuntimeError" not in response.text
        assert "scenario_ground_truth" not in response.text
        assert "C:\\private" not in response.text
        assert "RuntimeError" in caplog.text


def test_production_cors_rejects_wildcard(monkeypatch):
    from app.api.config import APISettings

    monkeypatch.setenv("TRACEX_ENV", "production")
    monkeypatch.setenv("TRACEX_CORS_ORIGINS", "*")
    try:
        APISettings.from_env()
    except ValueError as exc:
        assert "production" in str(exc)
    else:
        raise AssertionError("production wildcard CORS should be rejected")
