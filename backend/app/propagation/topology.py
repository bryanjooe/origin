"""Structural dependencies, not inferred fault paths or causal proof."""
import networkx as nx


def build_topology() -> nx.DiGraph:
    graph = nx.DiGraph()
    edges = [
        ("irradiance", "solar", "physical", "Irradiance determines PV power"),
        ("solar", "solar_sensor", "measurement", "Sensor measures PV output"),
        ("battery", "battery_sensor", "measurement", "Sensor reports stored energy"),
        ("demand", "demand_sensor", "measurement", "Meter measures AC demand"),
        ("solar_sensor", "communication", "information", "Timestamped PV reading"),
        ("battery_sensor", "communication", "information", "Timestamped SOC reading"),
        ("demand_sensor", "communication", "information", "Timestamped demand reading"),
        ("communication", "controller", "information", "Latest received packet drives dispatch"),
        ("firmware", "controller", "configuration", "Reserve and dispatch limits"),
        ("controller", "battery", "command", "Constrained battery dispatch"),
        ("controller", "inverter", "command", "Requested AC output"),
        ("solar", "inverter", "physical", "PV contributes to DC bus"),
        ("battery", "inverter", "physical", "Battery contributes to DC bus"),
        ("inverter", "delivered", "physical", "AC output serves demand"),
    ]
    for source, target, kind, description in edges:
        graph.add_edge(source, target, kind=kind, dependency=description,
                       suspected=False)
    for node in graph:
        graph.nodes[node]["label"] = node.replace("_", " ").title()
    return graph


def downstream(source: str) -> list[str]:
    graph = build_topology()
    if source not in graph:
        raise ValueError(f"Unknown component: {source}")
    return sorted(nx.descendants(graph, source) - {source})
