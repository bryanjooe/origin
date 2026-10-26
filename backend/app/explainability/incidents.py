"""Streaming incident grouping without fault schedules, hidden truth or future input."""
from collections import deque
from copy import deepcopy
import math

from app.localization.dataset import CLASSES, DISPLAY_NAMES, UNKNOWN
from app.propagation.investigation import incident_graph
from .evidence import collect_evidence, observable_sample
from .report import explain


def diagnosis_from(source):
    if source is None:
        return {"source": UNKNOWN, "model_predicted_source": None, "confidence": None,
                "source_model_available": False, "candidates": [],
                "reasons": ["Source model unavailable; no source prediction was fabricated"]}
    predicted = source["predicted_source"]
    if predicted not in (*CLASSES, UNKNOWN):
        raise ValueError("Unsupported source prediction")
    candidates = []
    for candidate in source["candidates"]:
        name, confidence = candidate["source"], float(candidate["confidence"])
        if name not in CLASSES or not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Invalid source candidate")
        candidates.append({"source": name, "label": DISPLAY_NAMES[name], "confidence": confidence})
    reasons = list(source["abstention_reasons"])
    if predicted == "normal":
        reasons.append("The classifier favors Normal despite an active anomaly alert")
    accepted = predicted not in (UNKNOWN, "normal")
    confidence = source["confidence"] if accepted else None
    if accepted and (confidence is None or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError("Accepted source predictions require a finite confidence")
    return {"source": predicted if accepted else UNKNOWN, "model_predicted_source": predicted,
            "confidence": confidence, "source_model_available": True,
            "confidence_kind": "uncalibrated_random_forest_probability", "candidates": candidates,
            "reasons": reasons}


def detection_record(value):
    record = {key: deepcopy(value[key]) for key in (
        "tick", "elapsed_seconds", "anomaly_score", "ml_status", "combined_status",
        "warning_threshold", "critical_threshold", "residual_checks")}
    score = record["anomaly_score"]
    if not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Anomaly score must be finite and in [0, 1]")
    if not 0 < record["warning_threshold"] < record["critical_threshold"] <= 1:
        raise ValueError("Invalid anomaly thresholds")
    for key in ("ml_status", "combined_status"):
        if record[key] not in ("normal", "warning", "critical"):
            raise ValueError("Unsupported anomaly status")
    record["residual_checks"] = [{key: check[key] for key in ("signal", "value", "threshold", "unit", "method")}
                                 for check in record["residual_checks"]]
    return record


class IncidentTracker:
    def __init__(self, *, confirmation_ticks: int = 3, recovery_ticks: int = 5):
        if (type(confirmation_ticks) is not int or confirmation_ticks < 1
                or type(recovery_ticks) is not int or recovery_ticks < 1):
            raise ValueError("Confirmation and recovery windows must be positive integers")
        self.confirmation_ticks, self.recovery_ticks = confirmation_ticks, recovery_ticks
        self.reset()

    def reset(self):
        self._pending = deque(maxlen=self.confirmation_ticks)
        self._active = None
        self._completed = []
        self._last_tick = self._last_elapsed = None
        self._next_id = 1

    def update(self, row, detection, source=None):
        sample = deepcopy(observable_sample(row))
        tick = sample["tick"]
        if type(tick) is not int or tick < 0:
            raise ValueError("tick must be a nonnegative integer")
        if self._last_tick is not None and (tick != self._last_tick + 1 or sample["elapsed_seconds"] <= self._last_elapsed):
            raise ValueError("Incident input must use consecutive time-ordered ticks")
        detection = detection_record(detection)
        for prediction in (detection, source):
            if prediction is not None and (prediction["tick"] != tick or prediction["elapsed_seconds"] != sample["elapsed_seconds"]):
                raise ValueError("Telemetry and model outputs must refer to the same tick and time")
        diagnosis = diagnosis_from(source)
        evidence = collect_evidence(sample, detection, source)
        alert = detection["combined_status"] != "normal"
        item = (sample, detection, diagnosis, evidence)
        self._last_tick, self._last_elapsed = tick, sample["elapsed_seconds"]
        if self._active is None:
            if not alert:
                self._pending.clear()
                return
            self._pending.append(item)
            if len(self._pending) < self.confirmation_ticks and detection["combined_status"] != "critical":
                return
            self._active = {"id": f"incident-{self._next_id:04d}", "status": "open",
                            "first_observed_tick": self._pending[0][0]["tick"], "detection_tick": tick,
                            "detection_time_seconds": sample["elapsed_seconds"],
                            "confirmation_delay_seconds": sample["elapsed_seconds"] - self._pending[0][0]["elapsed_seconds"],
                            "severity": detection["combined_status"], "peak_anomaly_score": -1.0,
                            "trigger_detection": detection, "last_alert_tick": tick, "resolved_at_tick": None,
                            "recovery_ticks": self.recovery_ticks, "quiet_ticks": 0,
                            "diagnosis": self._pending[0][2], "latest_diagnosis": self._pending[0][2],
                            "representative_tick": self._pending[0][0]["tick"],
                            "evidence": [], "samples": [], "timeline": [],
                            "as_of_tick": tick}
            self._next_id += 1
            for pending in self._pending:
                self._append(*pending)
            self._pending.clear()
            self._active["timeline"].append({"tick": tick, "elapsed_seconds": sample["elapsed_seconds"],
                                             "event": "incident_confirmed", "nodes": []})
            return
        self._append(*item)
        if alert:
            self._active["quiet_ticks"] = 0
        else:
            self._active["quiet_ticks"] += 1
            if self._active["quiet_ticks"] >= self.recovery_ticks:
                self._active["status"] = "resolved"
                self._active["resolved_at_tick"] = tick
                self._active["timeline"].append({"tick": tick, "elapsed_seconds": sample["elapsed_seconds"],
                                                 "event": "alerts_cleared", "nodes": []})
                self._completed.append(self._active)
                self._active = None

    def _append(self, sample, detection, diagnosis, evidence):
        incident = self._active
        previous_signals = {item["signal"] for item in incident["evidence"]}
        incident["samples"].append(sample)
        incident["as_of_tick"] = sample["tick"]
        if detection["combined_status"] == "critical":
            incident["severity"] = "critical"
        if detection["combined_status"] != "normal":
            if incident["latest_diagnosis"]["source"] != diagnosis["source"]:
                incident["timeline"].append({"tick": sample["tick"], "elapsed_seconds": sample["elapsed_seconds"],
                                             "event": "source_hypothesis_changed", "source": diagnosis["source"], "nodes": []})
            incident["latest_diagnosis"] = diagnosis
            if detection["anomaly_score"] >= incident["peak_anomaly_score"]:
                incident["peak_anomaly_score"] = detection["anomaly_score"]
                incident["diagnosis"] = diagnosis
                incident["representative_tick"] = sample["tick"]
            incident["last_alert_tick"] = sample["tick"]
        for item in evidence:
            incident["evidence"].append(item)
            if item["signal"] not in previous_signals:
                incident["timeline"].append({"tick": sample["tick"], "elapsed_seconds": sample["elapsed_seconds"],
                                             "event": "symptom_observed", "signal": item["signal"],
                                             "evidence_id": item["id"], "nodes": item["nodes"]})
                previous_signals.add(item["signal"])

    def reports(self, changed_since=None):
        reports = []
        for stored in [*self._completed, *([self._active] if self._active else [])]:
            if changed_since is not None and changed_since.get(stored["id"]) == (stored["as_of_tick"], stored["status"]):
                continue
            incident = deepcopy(stored)
            incident["timeline"].sort(key=lambda event: (event["tick"], event["event"]))
            graph = incident_graph(incident["diagnosis"], incident["evidence"], incident["samples"], incident["timeline"])
            incident["graph"] = graph
            incident["explanation"] = explain(incident, graph)
            reports.append(incident)
        return reports


def investigate(telemetry, detections, sources=None, **options):
    if len(telemetry) != len(detections) or sources is not None and len(sources) != len(telemetry):
        raise ValueError("Telemetry, detection and source sequences must have matching lengths")
    tracker = IncidentTracker(**options)
    for index, row in enumerate(telemetry):
        tracker.update(row, detections[index], sources[index] if sources is not None else None)
    return tracker.reports()
