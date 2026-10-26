"""Evidence-compatible structural paths, never proof of transmission or causation."""
import networkx as nx
from copy import deepcopy

from .topology import build_topology
from app.explainability.evidence import describe


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


SECURITY_LAYERS = {"Sensor": ["solar_sensor", "battery_sensor", "demand_sensor"],
                   "Communication": ["communication"], "Controller": ["controller"],
                   "Firmware-Config": ["firmware"], "Actuator-Inverter": ["inverter"]}
SECURITY_SIGNALS = {"Invalid authentication tags": ["communication"],
                    "Duplicate sequence numbers": ["communication"],
                    "Out-of-order sequence numbers": ["communication"],
                    "Configuration hash mismatches": ["firmware"],
                    "Controller policy inconsistencies": ["controller"],
                    "Solar redundant-sensor disagreements": ["solar_sensor"],
                    "Battery redundant-sensor disagreements": ["battery_sensor"]}


def evidence_graph(stored_graph, assessment, evidence):
    """Add a presentation overlay from persisted predictions and observations only.

    Phase 1 paths remain intact. Stage B paths are separately labeled structural
    hypotheses and require an accepted origin plus a recorded downstream symptom.
    """
    view = deepcopy(stored_graph)
    topology = build_topology()
    ids = {node["id"] for node in view.get("nodes", [])} & set(topology)
    assessment = assessment or {}
    accepted = assessment.get("available") and (assessment.get("nature_verdict") not in (None, "Undetermined")
        or assessment.get("origin_independent_of_nature", False))
    roots = [node for node in SECURITY_LAYERS.get(assessment.get("origin"), []) if node in ids] if accepted else []
    records = [item for item in evidence if item.get("id") and any(node in ids for node in item.get("nodes", []))]
    path_evidence, edge_evidence = {}, {}
    for root in roots:
        for item in records:
            for target in item.get("nodes", []):
                if target not in ids or root == target or not nx.has_path(topology, root, target):
                    continue
                path = nx.shortest_path(topology, root, target)
                if not set(path) <= ids:
                    continue
                path_evidence.setdefault(tuple(path), set()).add(item["id"])
                for a, b in zip(path, path[1:]):
                    edge_evidence.setdefault((a, b), set()).add(item["id"])
    paths = [{"nodes": list(path), "evidence_ids": sorted(refs), "basis": "Stage B origin hypothesis",
        "interpretation": "Structural dependency compatible with a recorded symptom; not observed transmission or causal proof"}
        for path, refs in sorted(path_evidence.items())]
    def explanation(item):
        try:
            return describe(item) if item.get("sample") else item.get("signal", "Recorded observation")
        except (KeyError, TypeError, ValueError):
            return f"{item.get('signal', 'Observation')} recorded; detailed measurement explanation unavailable."
    observations, observed_names = [], set()
    for group in (assessment.get("evidence") or {}).values():
        if isinstance(group, list):
            for item in group:
                if isinstance(item, dict) and item.get("name") in SECURITY_SIGNALS and item["name"] not in observed_names:
                    observations.append(item)
                    observed_names.add(item["name"])
    for node in view.get("nodes", []):
        name = node["id"]
        local = [item for item in records if name in item.get("nodes", [])]
        node["direct_evidence"] = [{key: item[key] for key in ("id", "tick", "signal", "value", "threshold", "unit", "kind", "nodes") if key in item}
                                   | {"description": explanation(item)}
                                   for item in local]
        node["security_observations"] = [item for item in observations if name in SECURITY_SIGNALS[item["name"]]]
        node["security_observed"] = any(isinstance(item.get("value"), str) and " of " in item["value"]
            and item["value"].split(" of ")[0].isdigit() and int(item["value"].split(" of ")[0]) > 0
            for item in node["security_observations"])
        node["security_candidate"] = name in roots
        node["security_potentially_affected"] = any(name in path["nodes"][1:] for path in paths)
        node["downstream_dependencies"] = sorted((nx.descendants(topology, name) - {name}) & ids) if name in topology else []
    for edge in view.get("edges", []):
        refs = sorted(edge_evidence.get((edge["source"], edge["target"]), []))
        edge.update(security_suspected=bool(refs), security_evidence_ids=refs)
    view["security_candidate_nodes"] = roots
    view["security_paths"] = paths
    view["security_origin_message"] = (f"Stage B suggests the {assessment['origin']} layer. All mapped components remain candidates; none is confirmed compromised."
        if roots else "Abnormal behavior was detected, but the available evidence is insufficient to identify a reliable security origin.")
    view["security_status"] = assessment.get("status", "unavailable")
    view["evidence_limitations"] = ["Phase 1 source localization and Stage B origin hypotheses are separate assessments.",
        "Downstream reachability is structural possibility, not evidence that a device was compromised.",
        "Timeline order does not establish causation; intermediate transmission times are not recorded."]
    return view
