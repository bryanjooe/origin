from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from app.api.analysis_service import AIAnalysisService
from app.api.config import APISettings
from app.api.errors import APIError
from app.api.main import create_app
from app.api.service import SimulationService
from pydantic import ValidationError
from app.persistence.artifacts import FileArtifactStore
from app.persistence.database import Database
from app.persistence.models import (
    AIAnalysisRecord,
    Base,
    FaultScenarioRecord,
    IncidentRecord,
    SimulationCommandRecord,
    SimulationResultMetadataRecord,
    SimulationRunRecord,
)
from app.persistence.repository import SQLAlchemyRepository
from app.simulator import GridConfig, MicrogridSimulator

PERSISTENCE_TOKEN = "persistence-test-token-0123456789abcdef0123456789"


def test_artifact_store_rejects_path_traversal_and_modified_chunks(tmp_path):
    store = FileArtifactStore(tmp_path / "artifacts")
    with pytest.raises(ValueError, match="Artifact path is invalid|outside"):
        store._resolve("../outside.json")
    with pytest.raises(ValueError, match="Artifact path is invalid|outside"):
        store._resolve(r"..\outside.json")

    artifact = store.write_telemetry_chunk("run", 0, 1, [{"tick": 0, "value": 1}])
    chunk = {"relative_path": artifact.relative_path, "size_bytes": artifact.size_bytes,
             "sha256": "0" * 64}
    with pytest.raises(ValueError, match="integrity"):
        store.read_telemetry_chunks([chunk], 0, 1)


def build_test_app(database_url: str, data_dir: Path):
    database = Database(database_url)
    repository = SQLAlchemyRepository(database.session_factory)
    artifact_store = FileArtifactStore(data_dir)
    service = SimulationService(repository, artifact_store)
    settings = APISettings(
        database_url=database_url,
        data_dir=str(data_dir),
        api_tokens={
            PERSISTENCE_TOKEN: "persistence-user",
            "export-test-key-0123456789abcdef0123456789": "persistence-user",
            "incident-test-key-0123456789abcdef0123456789": "persistence-user",
        },
    )
    app = create_app(
        settings=settings,
        service=service,
        database=database,
        artifact_store=artifact_store,
    )
    return app, database, repository, service


def create_repository_run(repository: SQLAlchemyRepository, run_id: str | None = None) -> str:
    run_id = run_id or str(uuid4())
    artifact = {"relative_path": f"runs/{run_id}/topology.json", "sha256": "a" * 64, "size_bytes": 2}
    repository.create_run(
        run_id=run_id,
        config=GridConfig().__dict__,
        seed=42,
        created_at=datetime.now(timezone.utc),
        initial_fault=None,
        topology_artifact=artifact,
        summary={"simulated_ticks": 0, "solar_generated_kwh": 0.0,
                 "demand_served_kwh": 0.0, "unmet_demand_kwh": 0.0,
                 "final_soc_pct": 60.0},
    )
    return run_id


def test_alembic_migration_creates_schema_without_destructive_downgrade(tmp_path, monkeypatch):
    database_path = tmp_path / "migration.sqlite"
    url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    monkeypatch.setenv("TRACEX_DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "head")

    engine = create_engine(url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "alembic_version",
        "simulation_runs",
        "fault_scenarios",
        "simulation_commands",
        "simulation_result_metadata",
        "incidents",
        "ai_analysis_records",
    }.issubset(tables)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0003_resource_owners"
    inspector = inspect(engine)
    for table in ("simulation_runs", "incidents", "ai_analysis_records"):
        assert "owner_id" in {column["name"] for column in inspector.get_columns(table)}
    engine.dispose()


def test_database_constraints_reject_invalid_faults_and_orphan_records():
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    repository = SQLAlchemyRepository(database.session_factory)
    run_id = create_repository_run(repository)

    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(FaultScenarioRecord(
                id=str(uuid4()), run_id=run_id, ordinal=1, fault_type="sensor", mode="bias",
                severity=1.1, duration_ticks=2, start_tick=0, scheduled_at_tick=0,
            ))
    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(IncidentRecord(
                id=str(uuid4()), simulation_run_id=str(uuid4()), title="orphan",
                affected_component="solar", category="operator_report", observed_evidence={},
                investigation_status="open",
            ))
    with pytest.raises(IntegrityError):
        with database.session_factory.begin() as session:
            session.add(AIAnalysisRecord(
                id=str(uuid4()), simulation_run_id=run_id, status="completed",
                schema_version="1", validated_output=None,
            ))
    database.dispose()


def test_advance_transaction_rolls_back_command_artifacts_and_simulator(tmp_path):
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    repository = SQLAlchemyRepository(database.session_factory)
    artifact_store = FileArtifactStore(tmp_path / "artifacts")
    service = SimulationService(repository, artifact_store)
    run = service.create_run(GridConfig(), 41)

    with database.engine.begin() as connection:
        connection.exec_driver_sql(
            """CREATE TRIGGER fail_controller_artifact BEFORE INSERT ON simulation_result_metadata
               WHEN NEW.artifact_type = 'controller_logs'
               BEGIN SELECT RAISE(ABORT, 'injected transaction failure'); END"""
        )

    with pytest.raises(APIError) as caught:
        service.advance(run.run_id, 3)
    assert caught.value.status_code == 503
    assert service.status(run.run_id)["current_tick"] == 0
    with database.session_factory() as session:
        assert session.scalar(select(SimulationRunRecord.current_tick).where(
            SimulationRunRecord.id == run.run_id
        )) == 0
        assert session.scalar(select(SimulationCommandRecord.id).where(
            SimulationCommandRecord.run_id == run.run_id
        )) is None
        assert session.scalar(select(SimulationResultMetadataRecord.id).where(
            SimulationResultMetadataRecord.run_id == run.run_id,
            SimulationResultMetadataRecord.artifact_type == "telemetry",
        )) is None
    assert not list((tmp_path / "artifacts" / "runs" / run.run_id).glob("telemetry-*.jsonl"))
    database.dispose()


def test_run_and_telemetry_survive_application_restart_and_replay_deterministically(tmp_path):
    database_path = tmp_path / "persistent.sqlite"
    database_url = f"sqlite+pysqlite:///{database_path.as_posix()}"
    first_app, first_db, _, _ = build_test_app(database_url, tmp_path / "managed-results")
    Base.metadata.create_all(first_db.engine)

    with TestClient(first_app, headers={"Authorization": f"Bearer {PERSISTENCE_TOKEN}"}) as client:
        created = client.post(
            "/api/v1/runs",
            json={
                "seed": 82,
                "config": {"start_hour": 17.0},
                "fault": {
                    "kind": "sensor", "mode": "bias", "severity": 0.5,
                    "duration_ticks": 4, "start_tick": 0,
                },
            },
        )
        assert created.status_code == 201, created.text
        run_id = created.json()["run_id"]
        incident = client.post(
            "/api/v1/incidents",
            headers={"Authorization": f"Bearer {PERSISTENCE_TOKEN}"},
            json={
                "simulation_run_id": run_id,
                "title": "Persisted operator report",
                "affected_component": "solar",
                "category": "operator_report",
                "observed_evidence": {"source": "test fixture"},
            },
        )
        assert incident.status_code == 201
        incident_id = incident.json()["id"]
        assert client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 2}).status_code == 200
        scheduled = client.post(
            f"/api/v1/runs/{run_id}/fault-schedules",
            json={
                "kind": "inverter", "mode": "derate", "severity": 0.7,
                "duration_ticks": 2, "start_tick": 4,
            },
        )
        assert scheduled.status_code == 201
        assert client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 3}).status_code == 200
        assert client.post(f"/api/v1/runs/{run_id}/correct").status_code == 200
        assert client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 2}).status_code == 200
        before_restart = client.get(f"/api/v1/runs/{run_id}/telemetry").json()["rows"]
        results = client.get(f"/api/v1/runs/{run_id}/results").json()
        assert {item["artifact_type"] for item in results["artifacts"]} >= {
            "telemetry", "controller_logs", "topology_snapshot", "output_summary"
        }
        assert "relative_path" not in results["artifacts"][0]
    first_db.dispose()

    second_app, second_db, _, _ = build_test_app(database_url, tmp_path / "managed-results")
    with TestClient(second_app, headers={"Authorization": f"Bearer {PERSISTENCE_TOKEN}"}) as client:
        status = client.get(f"/api/v1/runs/{run_id}")
        assert status.status_code == 200
        assert status.json()["current_tick"] == 7
        persisted_incident = client.get(
            f"/api/v1/incidents/{incident_id}",
            headers={"Authorization": f"Bearer {PERSISTENCE_TOKEN}"},
        )
        assert persisted_incident.status_code == 200
        assert persisted_incident.json()["title"] == "Persisted operator report"
        after_restart = client.get(f"/api/v1/runs/{run_id}/telemetry").json()["rows"]
        assert after_restart == before_restart
        assert "scenario_ground_truth" not in client.get(
            f"/api/v1/runs/{run_id}/exports/json",
            headers={"Authorization": f"Bearer {PERSISTENCE_TOKEN}"},
        ).text
        continued = client.post(f"/api/v1/runs/{run_id}/advance", json={"ticks": 1})
        assert continued.status_code == 200
        all_rows = client.get(f"/api/v1/runs/{run_id}/telemetry").json()["rows"]

    expected = MicrogridSimulator(GridConfig(start_hour=17.0), seed=82)
    expected.inject("sensor", "bias", severity=0.5, duration_ticks=4, start_tick=0)
    expected.run(2)
    expected.inject("inverter", "derate", severity=0.7, duration_ticks=2, start_tick=4)
    expected.run(3)
    expected.correct()
    expected.run(3)
    assert all_rows == expected.history
    second_db.dispose()


def test_ai_analysis_statuses_and_validated_output(tmp_path):
    database = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(database.engine)
    repository = SQLAlchemyRepository(database.session_factory)
    run_id = create_repository_run(repository)
    service = AIAnalysisService(repository)
    analysis_id = service.create_pending(simulation_run_id=run_id)
    assert service.get(analysis_id)["status"] == "pending"
    assert service.get(analysis_id)["validated_output"] is None
    service.mark_running(analysis_id, model_name="external-component", model_version="v1")
    with pytest.raises(ValidationError):
        service.complete(analysis_id, {
            "schema_version": "1",
            "summary": "invalid component",
            "findings": [{"component": "not-in-topology", "finding": "x", "evidence_refs": ["tick:0"]}],
        })
    assert service.get(analysis_id)["status"] == "running"
    service.complete(analysis_id, {
        "schema_version": "1",
        "summary": "A test fixture output, not a model prediction.",
        "findings": [{"component": "solar", "finding": "Evidence fixture.", "evidence_refs": ["telemetry.tick:0"]}],
    }, model_name="external-component", model_version="v1")
    completed = service.get(analysis_id)
    assert completed["status"] == "completed"
    assert completed["validated_output"]["findings"][0]["component"] == "solar"

    failed_id = service.create_pending(simulation_run_id=run_id)
    service.fail(failed_id, "model_unavailable", "The external component was unavailable.")
    failed = service.get(failed_id)
    assert failed["status"] == "failed"
    assert failed["validated_output"] is None
    database.dispose()
