import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_path():
    # Keep exports inside the project under restricted desktop environments.
    parent = ROOT / "outputs" / "test-temp"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        yield Path(directory)


def run_cli(*args):
    return subprocess.run([sys.executable, "-m", "app.simulator", *args],
                          cwd=ROOT, env={**os.environ, "PYTHONPATH": str(ROOT / "backend")},
                          capture_output=True, text=True, timeout=30)


def test_cli_exports_and_corrective_action(tmp_path):
    result = run_cli("--ticks", "30", "--fault", "inverter", "--mode", "shutdown",
                     "--start", "5", "--duration", "20", "--correct-at", "15",
                     "--output", str(tmp_path))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["ticks"] == 30
    telemetry = json.loads((tmp_path / "telemetry.json").read_text())
    truth = json.loads((tmp_path / "scenario_ground_truth.json").read_text())
    topology = json.loads((tmp_path / "topology.json").read_text())
    assert truth["faults"][0]["cancelled_at_tick"] == 15
    assert truth["faults"][0]["duration_ticks"] == 20
    assert telemetry[5]["inverter_actual_kw"] == 0
    assert telemetry[15]["inverter_actual_kw"] > 0
    assert "faults" not in telemetry[5] and "severity" not in telemetry[5]
    assert topology["nodes"] and topology["edges"]
    with (tmp_path / "telemetry.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 30
    assert json.loads(rows[0]["controller_inputs"])["source_tick"] == 0


@pytest.mark.parametrize("args", [
    ["--ticks", "0"], ["--ticks", "10", "--correct-at", "10"],
    ["--fault", "sensor", "--mode", "shutdown"],
    ["--fault", "inverter", "--severity", "2"],
])
def test_cli_validation(args):
    result = run_cli(*args)
    assert result.returncode == 2
    assert "error:" in result.stderr
