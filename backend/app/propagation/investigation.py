"""Evidence-compatible structural paths, never proof of transmission or causation."""
import networkx as nx

from .topology import build_topology


SOURCE_NODES = {"communication": ["communication"], "controller": ["controller"],
                "firmware": ["firmware"], "inverter": ["inverter"]}
NODE_FIELDS = {
    "irradiance": ["expected_solar_kw"], "solar": ["expected_solar_kw"],
    "solar_sensor": ["measured_solar_kw", "expected_solar_kw"],
    "battery": ["battery_power_kw"], "battery_sensor": ["measured_soc_pct"],
    "demand": ["demand_kw"], "demand_sensor": ["demand_kw"],
    "communication": ["message_age_seconds", "message_source_tick", "controller_inputs"],
    "controller": ["controller_inputs", "controller_command_kw", "inverter_requested_kw"],
    "firmware": ["applied_reserve_soc_pct", "applied_discharge_limit_kw", "config_integrity_ok"],
    "inverter": ["inverter_requested_kw", "inverter_actual_kw"],
    "delivered": ["demand_kw", "delivered_kw", "unmet_demand_kw"],
}


def incident_graph(diagnosis, evidence, samples, timeline):
    graph = build_topology()
    latest = {}
    for item in evidence:
        latest[item["signal"]] = item
    roots = list(SOURCE_NODES.get(diagnosis["source"], []))
    if diagnosis["source"] == "sensor":
        roots = sorted({node for item in latest.values() if item["kind"] == "residual_observation"
                        for node in item["nodes"] if node in ("solar_sensor", "battery_sensor")})
        if not roots:
            roots = ["solar_sensor", "battery_sensor"]
    observed = {node for item in latest.values() for node in item["nodes"]}
    suspected_edges = {}
    paths = []
    for root in roots:
        for item in latest.values():
            for target in item["nodes"]:
                if root == target or not nx.has_path(graph, root, target):
                    continue
                path = nx.shortest_path(graph, root, target)
                paths.append({"nodes": path, "evidence_ids": [item["id"]],
                              "interpretation": "Known dependency path compatible with an observed symptom; not causal proof"})
                for a, b in zip(path, path[1:]):
                    suspected_edges.setdefault((a, b), set()).add(item["id"])
    nodes = []
    for node, data in graph.nodes(data=True):
        history = [{"tick": sample["tick"], "elapsed_seconds": sample["elapsed_seconds"],
                    **{key: sample[key] for key in NODE_FIELDS[node]}} for sample in samples]
        nodes.append({"id": node, **data, "candidate_source": node in roots,
                      "observed_symptom": node in observed,
                      "potentially_affected": any(node in path["nodes"][1:] for path in paths),
                      "evidence_ids": [item["id"] for item in latest.values() if node in item["nodes"]],
                      "telemetry": history,
                      "events": [event for event in timeline if node in event.get("nodes", [])]})
    edges = []
    for a, b, data in graph.edges(data=True):
        ids = sorted(suspected_edges.get((a, b), []))
        edges.append({"source": a, "target": b, **data, "suspected": bool(ids),
                      "evidence_ids": ids,
                      "evidence_scope": "downstream symptom on a structural path" if ids else "known dependency only",
                      "uncertainty": "Intermediate transmission is not directly established" if ids else None})
    return {"nodes": nodes, "edges": edges, "suspected_paths": paths,
            "candidate_source_nodes": roots, "observed_nodes": sorted(observed),
            "potentially_affected_nodes": sorted({node for path in paths for node in path["nodes"][1:]}),
            "as_of_tick": samples[-1]["tick"],
            "limitations": ["Temporal ordering and dependency paths do not establish causation",
                            "Observed downstream symptoms may have competing explanations",
                            "One shortest structural path is shown per candidate and symptom; alternative routes may exist"]}
