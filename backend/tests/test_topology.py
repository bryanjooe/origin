import networkx as nx
import pytest

from app.propagation import build_topology, downstream


def test_documented_dependencies():
    graph = build_topology()
    assert isinstance(graph, nx.DiGraph)
    assert nx.has_path(graph, "solar_sensor", "delivered")
    assert nx.has_path(graph, "firmware", "controller")
    assert "controller" in downstream("communication")
    assert "delivered" in downstream("communication")
    assert "irradiance" not in downstream("controller")
    assert "controller" not in downstream("controller")
    assert downstream("delivered") == []
    for _, _, data in graph.edges(data=True):
        assert data["dependency"] and data["kind"]
        assert not data["suspected"]


def test_unknown_node():
    with pytest.raises(ValueError, match="Unknown component"):
        downstream("nonexistent")
