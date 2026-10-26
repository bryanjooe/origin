"""Presentation-only graph overlays; predictions below are explicit unit fixtures."""
from copy import deepcopy

from fastapi.testclient import TestClient
import pytest

from app.api.config import ServerSettings
from app.detection import AnomalyDetector, FeatureExtractor
from app.explainability.incidents import investigate
from app.main import create_app
from app.propagation import build_topology
from app.propagation.investigation import evidence_graph
from app.simulator import GridConfig, MicrogridSimulator


@pytest.fixture(scope="module")
def report():
    simulator = MicrogridSimulator(GridConfig(start_hour=16), seed=42)
    simulator.inject("inverter", "shutdown", start_tick=5, duration_ticks=20)
    rows = simulator.run(30)
    detector = AnomalyDetector.load(ServerSettings().anomaly_model)
    statuses = detector.predict(FeatureExtractor(simulator.config).transform(rows))
    return investigate(rows, statuses)[0]


@pytest.mark.parametrize("origin,expected", [
    ("Sensor", ["solar_sensor", "battery_sensor", "demand_sensor"]),
    ("Communication", ["communication"]), ("Controller", ["controller"]),
    ("Firmware-Config", ["firmware"]), ("Actuator-Inverter", ["inverter"]),
])
def test_stage_b_layers_map_to_topology_without_arbitrary_sensor_choice(report, origin, expected):
    assessment = {"available": True, "status": "available", "nature_verdict": "Cyber attack", "origin": origin}
    graph = evidence_graph(report["graph"], assessment, report["evidence"])
    assert graph["security_candidate_nodes"] == expected
    assert {node["id"] for node in graph["nodes"] if node["security_candidate"]} == set(expected)
    assert graph["candidate_source_nodes"] == report["graph"]["candidate_source_nodes"]
    topology = build_topology()
    refs = {item["id"] for item in report["evidence"]}
    for path in graph["security_paths"]:
        assert set(path["evidence_ids"]) <= refs
        assert path["nodes"][0] in expected
        assert all(topology.has_edge(a, b) for a, b in zip(path["nodes"], path["nodes"][1:]))
        assert "not observed transmission" in path["interpretation"]


@pytest.mark.parametrize("assessment", [None,
    {"available": False, "status": "pending"}, {"available": False, "status": "unavailable"},
    {"available": True, "nature_verdict": "Undetermined", "origin": "Communication"},
    {"available": True, "nature_verdict": "Cyber attack", "origin": "Unknown"},
])
def test_unknown_pending_and_unavailable_never_fabricate_security_paths(report, assessment):
    original = deepcopy(report["graph"])
    graph = evidence_graph(original, assessment, report["evidence"])
    assert graph["security_candidate_nodes"] == [] and graph["security_paths"] == []
    assert not any(edge["security_suspected"] for edge in graph["edges"])
    assert graph["observed_nodes"] == original["observed_nodes"]
    assert graph["suspected_paths"] == original["suspected_paths"]
    assert original == report["graph"]
    assert "insufficient" in graph["security_origin_message"]


def test_node_evidence_telemetry_and_timeline_remain_actual_recorded_values(report):
    graph = evidence_graph(report["graph"], None, report["evidence"])
    originals = {node["id"]: node for node in report["graph"]["nodes"]}
    evidence = {item["id"]: item for item in report["evidence"]}
    for node in graph["nodes"]:
        assert node["telemetry"] == originals[node["id"]]["telemetry"]
        assert node["events"] == originals[node["id"]]["events"]
        assert node["id"] not in node["downstream_dependencies"]
        for item in node["direct_evidence"]:
            assert item["id"] in evidence and node["id"] in evidence[item["id"]]["nodes"]
            assert item["tick"] == evidence[item["id"]]["tick"]
            assert item["value"] == evidence[item["id"]]["value"]
        for event in node["events"]:
            assert event in report["timeline"]
    assert {(edge["source"], edge["target"]) for edge in graph["edges"]} == set(build_topology().edges)


def test_missing_evidence_does_not_generate_propagation_or_measurements(report):
    graph = evidence_graph(report["graph"], {"available": True, "nature_verdict": "Cyber attack", "origin": "Communication"}, [])
    assert graph["security_paths"] == []
    assert all(node["direct_evidence"] == [] for node in graph["nodes"])


def test_positive_security_counts_are_observations_not_origin_claims(report):
    assessment = {"available": True, "nature_verdict": "Undetermined", "origin": "Unknown", "evidence": {
        "points_toward_attack": [{"name": "Invalid authentication tags", "value": "2 of 20", "unit": "messages", "window_ticks": 20}]}}
    graph = evidence_graph(report["graph"], assessment, [])
    communication = next(node for node in graph["nodes"] if node["id"] == "communication")
    assert communication["security_observed"] and not communication["security_candidate"]
    assert communication["security_observations"][0]["value"] == "2 of 20"
    assert graph["security_paths"] == []


@pytest.mark.parametrize("scenario", ["fault", "attack"])
def test_graph_api_is_additive_and_independent_of_injected_labels(workspace_tmp_path, scenario):
    with TestClient(create_app(ServerSettings(database_path=workspace_tmp_path / "graph.sqlite3"))) as client:
        path = "inject-attack" if scenario == "attack" else "inject-fault"
        body = {"attack_type": "actuator_abuse", "target_component": "inverter", "stealth_level": "naive"} if scenario == "attack" else {"kind": "inverter", "mode": "shutdown"}
        response = client.post(f"/api/simulation/{path}", json={**body, "severity": 1, "duration_ticks": 120})
        assert response.status_code == 200
        assert client.post("/api/simulation/step", json={"ticks": 40}).status_code == 200
        runtime = client.app.state.runtime
        item = client.get("/api/incidents").json()["data"]["items"][0]
        original = runtime.store.incident(item["id"])
        graph = client.get(f"/api/incidents/{item['id']}/graph").json()["data"]
        detail = client.get(f"/api/incidents/{item['id']}").json()["data"]
        assert graph == detail["graph"]
        assert detail["diagnosis"] == original["diagnosis"]
        assert detail["security_attribution"] == original["security_attribution"]
        metadata = runtime.metadata()
        metadata["ground_truth"] = {"attack_type": "replay", "target_component": "communication"}
        runtime.store.update_scenario(runtime.run_id, "paused", metadata)
        assert client.get(f"/api/incidents/{item['id']}/graph").json()["data"] == graph
        assert runtime.store.incident(item["id"])["graph"] == original["graph"]
        if detail["security_attribution"]["origin"] == "Unknown":
            assert graph["security_candidate_nodes"] == [] and graph["security_paths"] == []
