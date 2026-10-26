"""Exercise a local running backend with real saved models and retain measured results."""
import argparse
import json
from pathlib import Path
import time

import httpx


def main():
    parser = argparse.ArgumentParser(description="Run a seeded fault/correction API demo; archives the current scenario")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path("outputs/stage5-live-check.json"))
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        def get(path, **kwargs):
            response = client.get(path, **kwargs)
            response.raise_for_status()
            return response.json()["data"]
        def post(path, body=None):
            response = client.post(path, json=body) if body is not None else client.post(path)
            response.raise_for_status()
            return response.json()["data"]
        health = get("/api/health")
        if not all(value["available"] for value in health["models"].values()):
            raise RuntimeError("Train both models before running the complete API demo")
        post("/api/simulation/pause")
        state = post("/api/simulation/scenario", {"seed": 42, "fault": {
            "kind": "inverter", "mode": "derate", "severity": 0.8, "start_tick": 30, "duration_ticks": 120}})
        run_id = state["run_id"]
        post("/api/simulation/step", {"ticks": 80})
        before = get("/api/metrics/sustainability")
        post("/api/simulation/correct")
        post("/api/simulation/step", {"ticks": 60})
        listing = get("/api/incidents", params={"run_id": run_id})
        if not listing["items"]:
            raise AssertionError("Expected a real detected incident")
        incidents = [get(f"/api/incidents/{item['id']}") for item in listing["items"]]
        graphs = [get(f"/api/incidents/{item['id']}/graph") for item in listing["items"]]
        sustainability = get("/api/metrics/sustainability")
        assert sustainability["estimated_correction_delivery_gain_kwh"] > 0
        assert all(abs(item["energy_balance_residual_kwh"]) < 1e-8 for item in sustainability["comparison"].values())
        exported = client.get("/api/reports/export", params={"dataset": "incidents", "format": "csv", "run_id": run_id})
        exported.raise_for_status()
        post("/api/model/evaluate", {"profile": "quick"})
        deadline = time.monotonic() + 60
        while True:
            metrics = get("/api/model/metrics")
            if metrics["evaluation"]["status"] != "running":
                break
            if time.monotonic() >= deadline:
                raise TimeoutError("Held-out quick evaluation did not finish within 60 seconds")
            time.sleep(0.2)
        assert metrics["evaluation"]["status"] == "complete", metrics["evaluation"]
        report = {"scope": "Measured local HTTP workflow; not an incident-accuracy benchmark", "health": health,
                  "run_id": run_id, "ticks": get("/api/system/state")["next_tick"],
                  "incident_summaries": [{key: incident[key] for key in (
                      "id", "status", "detection_tick", "representative_tick", "resolved_at_tick", "diagnosis")}
                      for incident in incidents],
                  "suspected_edges": [[{"source": edge["source"], "target": edge["target"], "evidence_ids": edge["evidence_ids"]}
                                       for edge in graph["edges"] if edge["suspected"]] for graph in graphs],
                  "before_correction": before, "sustainability": sustainability,
                  "csv_export_bytes": len(exported.content), "evaluation": metrics["evaluation"],
                  "evaluation_summary": {name: {"profile": value["profile"], "provenance": value["provenance"],
                      **({"normal_rows": value["report"]["normal_rows"], "fault_rows": value["report"]["fault_rows"],
                          "performance": value["report"]["performance"]} if name == "anomaly" else {
                          key: value["report"][key] for key in ("rows", "run_count", "accuracy_including_unknown", "coverage", "accepted_accuracy")})}
                      for name, value in metrics["reports"].items()}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"ticks": report["ticks"], "incidents": len(incidents),
                      "correction_delivery_gain_kwh": sustainability["estimated_correction_delivery_gain_kwh"],
                      "evaluation_status": metrics["evaluation"]["status"], "output": str(args.output.resolve())}, indent=2))


if __name__ == "__main__":
    main()
