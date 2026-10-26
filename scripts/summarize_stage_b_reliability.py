"""Derive additional metrics from saved predictions, without fitting or rescoring."""
from collections import Counter
import json
from pathlib import Path

from app.security_analysis.evaluation import _classification
from app.security_analysis.model import NATURE_DISPLAY, ORIGIN_DISPLAY
from evaluate_stage_b_reliability import summary, task_metrics


def details(report, starts):
    rows = report["row_level_results"]
    detected = [row for row in rows if row["inference_tick"] is not None]
    known = [row for row in detected if row["origin_truth"] is not None]
    result = summary(report)
    result["metric_definitions"] = [
        "Macro-F1 uses the existing fixed class lists, including the abstention output class with zero true examples.",
        "Classifier coverage and accepted accuracy are conditional on a complete detected window.",
        "All-run classification coverage excludes unalerted runs; unalerted normal operational states are not claimed as classifier predictions.",
        "Overall accuracy counts event detector misses and abstentions as incorrect; unalerted normal runs count as correct operational Normal states.",
        "Event windows are selected for offline scoring only after observable incident windows are built; ground truth never enters feature extraction."]
    result["conditional_on_detection"] = {
        "nature": _classification([NATURE_DISPLAY[row["nature_truth"]] for row in detected], [row["nature_prediction"] for row in detected], [*NATURE_DISPLAY.values(), "Undetermined"]),
        "origin": _classification([ORIGIN_DISPLAY[row["origin_truth"]] for row in known], [row["origin_prediction"] for row in known], [*ORIGIN_DISPLAY.values(), "Unknown"])}
    result["overall_per_class_and_confusion"] = {"nature": report["nature"], "origin": report["origin"]}
    result["counts_by_origin"] = dict(Counter(row["origin_truth"] or "not_applicable" for row in rows))
    result["by_attack_type"] = {}
    result["by_severity"] = {}
    result["by_stealth"] = {}
    for field, output in (("scenario_type", "by_attack_type"), ("severity", "by_severity"), ("stealth_level", "by_stealth")):
        for key in sorted({str(row[field]) for row in rows if row["nature_truth"] == "attack"}):
            group = [row for row in rows if row["nature_truth"] == "attack" and str(row[field]) == key]
            result[output][key] = {"nature": task_metrics(group, "nature"), "origin": task_metrics(group, "origin")}
    result["delay_by_nature"] = {}
    for nature in ("normal", "fault", "attack"):
        group = [row for row in detected if row["nature_truth"] == nature and row["run_id"] in starts]
        result["delay_by_nature"][nature] = {"detected_count": len(group),
            "mean_detection_ticks": sum(row["detector_fire_tick"] - starts[row["run_id"]] for row in group) / len(group) if group else None,
            "mean_classification_ticks": sum(row["inference_tick"] - starts[row["run_id"]] for row in group) / len(group) if group else None}
    return result


def main():
    root = Path("outputs/step5")
    old = json.loads((root / "original/metadata.json").read_text())
    fresh = json.loads((root / "candidates/corpus.json").read_text())
    starts = {run["run_id"]: run["start_tick"] for run in old["run_manifests"] + fresh["run_manifests"]}
    reports = [root / f"original_{name}_baseline.json" for name in ("held_out", "stealth_generalization")]
    reports.extend(path for path in (root / "candidates").rglob("*.json")
                   if path.name.endswith("evaluation.json") or path.name in ("baseline_held_out.json", "baseline_validation.json"))
    for path in reports:
        report = json.loads(path.read_text())
        if "row_level_results" not in report:
            continue
        target = path.with_name(path.stem + "_reliability.json")
        target.write_text(json.dumps(details(report, starts), indent=2, allow_nan=False), encoding="utf-8")
        print(target, flush=True)


if __name__ == "__main__":
    main()
