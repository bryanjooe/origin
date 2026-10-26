import asyncio
from copy import deepcopy
from dataclasses import asdict
import uuid

from app.database import Store
from app.detection import FeatureExtractor
from app.explainability.incidents import IncidentTracker
from app.localization import LocalizationFeatureExtractor
from app.simulator import GridConfig, MicrogridSimulator
from app.sustainability import EnergyLedger
from app.security_analysis import extract_window
from app.security_analysis.attribution import build_attribution
from .models import ModelRegistry


class RuntimeConflict(ValueError):
    pass


class SimulationRuntime:
    def __init__(self, settings):
        self.settings = settings
        self.store = Store(settings.database_path)
        self.store.recover_interrupted()
        self.models = ModelRegistry(settings)
        saved = self.store.latest_evaluation()
        if saved and saved["artifacts"] == self.models.fingerprints:
            self.models.reports = saved["reports"]
        self.lock = asyncio.Lock()
        self.running_event, self.changed = asyncio.Event(), asyncio.Event()
        self.task = self.evaluation_task = None
        self.evaluation = {"status": "idle"}
        self.running = self.closed = False
        self.speed = 2.0
        self.error = None
        self._new_run(GridConfig(), 42)

    def _new_run(self, config, seed):
        self.run_id = uuid.uuid4().hex
        self.sim = MicrogridSimulator(config, seed)
        self.baseline = MicrogridSimulator(config, seed)
        self.uncorrected = MicrogridSimulator(config, seed)
        self.ledgers = {name: EnergyLedger(config) for name in ("baseline", "faulty_uncorrected", "operated")}
        self.extractor = FeatureExtractor(config)
        self.source_extractor = LocalizationFeatureExtractor(config)
        self.tracker = IncidentTracker()
        self._versions = {}
        self.latest_anomaly = self.latest_source = None
        self._event_index = 0
        self.correction_ticks = []
        self.error = None
        self.store.create_scenario(self.run_id, self.metadata())
        self.store.event(self.run_id, 0, "scenario_created")

    def metadata(self):
        return {**self.sim.settings(), "next_tick": self.sim.tick,
                "model_artifact_sha256": dict(self.models.fingerprints),
                "ground_truth": {"label": "Simulated scenario truth; not inference input",
                                 "faults": self.sim.faults.ground_truth()},
                "uncorrected_counterfactual_faults": self.uncorrected.faults.ground_truth(),
                "correction_ticks": list(self.correction_ticks), "sustainability": self.sustainability()}

    def sustainability(self):
        snapshots = {name: ledger.snapshot() for name, ledger in self.ledgers.items()}
        baseline, faulty, operated = (snapshots[name] for name in ("baseline", "faulty_uncorrected", "operated"))
        difference = baseline["delivered_kwh"] - faulty["delivered_kwh"]
        return {"comparison": snapshots,
                "estimated_fault_delivery_loss_kwh": max(0, difference),
                "signed_baseline_minus_faulty_delivery_kwh": difference,
                "estimated_correction_delivery_gain_kwh": operated["delivered_kwh"] - faulty["delivered_kwh"],
                "correction_ticks": list(self.correction_ticks),
                "assumptions": ["Paired seeded simulations have identical weather/demand and equal horizons",
                                "Initial battery energy has unknown provenance and is not counted as renewable",
                                "Stored renewable/unknown energy mixes proportionally; charging uses solar only",
                                "Unused DC can include wasted battery discharge; solar curtailment is allocated proportionally",
                                "Loss/gain comparisons are simulated counterfactual estimates, not measured causal effects",
                                "Efficiencies are energy ratios; round-trip figure is the configured product, not a measured cycle",
                                "No emissions factor is configured; no carbon savings are claimed"]}

    def state(self):
        return {"run_id": self.run_id, "running": self.running, "speed_ticks_per_second": self.speed,
                "next_tick": self.sim.tick, "simulated_seconds": self.sim.tick * self.sim.config.tick_seconds,
                "config": asdict(self.sim.config), "telemetry": deepcopy(self.sim.history[-1]) if self.sim.history else None,
                "anomaly": deepcopy(self.latest_anomaly), "source": deepcopy(self.latest_source),
                "models": self.models.availability(), "runtime_error": self.error,
                "worker_active": self.task is not None and not self.task.done()}

    def _reports(self):
        reports = self.tracker.reports(changed_since=self._versions)
        for report in reports:
            self._versions[report["id"]] = (report["as_of_tick"], report["status"])
        return reports

    def security_attribution(self, report):
        """Classify an incident from persisted observable telemetry only."""
        model = self.models.security_analyzer
        if model is None:
            return {"available": False, "nature_verdict": "Undetermined",
                    "nature_confidence": None, "origin": "Unknown",
                    "reason": "Security attribution model is not available."}
        run_id = report.get("run_id")
        if not run_id:
            return {"available": False, "nature_verdict": "Undetermined",
                    "nature_confidence": None, "origin": "Unknown",
                    "reason": "Incident run identity is unavailable."}

        first_tick = report.get("first_observed_tick", report.get("detection_tick"))
        if not isinstance(first_tick, int):
            return {"available": False, "nature_verdict": "Undetermined",
                    "nature_confidence": None, "origin": "Unknown",
                    "reason": "Anomaly onset tick is unavailable."}
        policy = self.models.security_policy
        if policy is None:
            return {"available": False, "nature_verdict": "Undetermined",
                    "nature_confidence": None, "origin": "Unknown",
                    "reason": "The training-calibrated alert policy is unavailable."}
        observed_through = report.get("as_of_tick")
        if not isinstance(observed_through, int):
            observed_through = first_tick
        from app.security_analysis.dataset import _first_policy_fire
        detection_rows = self.store.telemetry(run_id, first_tick - 1,
                                               max(1, observed_through - first_tick + 1))
        statuses = [{"tick": item["telemetry"]["tick"],
                     "anomaly_score": (item.get("anomaly") or {}).get("anomaly_score", 0.0),
                     "residual_checks": (item.get("anomaly") or {}).get("residual_checks", [])}
                    for item in detection_rows if item.get("anomaly") is not None]
        fire_tick = _first_policy_fire(statuses, policy)
        if fire_tick is None:
            return {"available": False, "nature_verdict": "Undetermined",
                    "nature_confidence": None, "origin": "Unknown",
                    "reason": "The calibrated Stage B alert gate has not fired in this incident window."}
        inference_tick = min(observed_through, fire_tick + 19)
        before = self.store.telemetry(run_id, max(-1, fire_tick - 21), 21)
        after = self.store.telemetry(run_id, fire_tick - 1, 20)
        baseline = [item["telemetry"] for item in before
                    if item.get("telemetry", {}).get("tick", inference_tick) < fire_tick]
        rows = [item["telemetry"] for item in after
                if fire_tick <= item.get("telemetry", {}).get("tick", -1) <= inference_tick]
        if not rows:
            return {"available": False, "nature_verdict": "Undetermined",
                    "nature_confidence": None, "origin": "Unknown",
                    "reason": "Insufficient post-alert telemetry for a causal window."}

        scenario = self.store.scenario(run_id) or {}
        metadata = scenario.get("metadata", {})
        config_fields = set(GridConfig.__dataclass_fields__)
        config = GridConfig(**{key: value for key, value in metadata.items() if key in config_fields})
        try:
            features = extract_window(rows, solar_capacity_kw=config.solar_capacity_kw,
            battery_capacity_kwh=config.battery_capacity_kwh, tick_seconds=config.tick_seconds,
            communication_delay_ticks=config.communication_delay_ticks,
            charge_efficiency=config.charge_efficiency,
            discharge_efficiency=config.discharge_efficiency, baseline_rows=baseline)
            prediction = model.predict_features(features)
        except (KeyError, TypeError, ValueError) as error:
            return {"available": False, "nature_verdict": "Undetermined",
                    "nature_confidence": None, "origin": "Unknown",
                    "reason": f"Telemetry window could not be evaluated: {error}"}
        if not prediction.get("available"):
            return {**prediction, "reason": "The security classifier is not trained."}
        attribution = build_attribution(rows, prediction)
        return {**prediction, "nature_verdict": prediction.get("nature", "Undetermined"),
                "ranked_origin_layers": prediction.get("origin_candidates", []),
                "evidence": attribution,
                "inference_tick": inference_tick,
                "window_ticks": len(rows),
                "provenance": "observable telemetry only; indicators are not proof of intent"}

    def _advance(self):
        row = self.sim.step()
        normal = self.baseline.step()
        uncorrected = self.uncorrected.step()
        observation = self.extractor.update(row)
        source_observation = self.source_extractor.update(row)
        self.latest_anomaly = self.models.detector.predict([observation])[0] if self.models.detector else None
        self.latest_source = self.models.localizer.predict([source_observation])[0] if self.models.localizer else None
        if self.latest_anomaly:
            self.tracker.update(row, self.latest_anomaly, self.latest_source)
        for name, data in (("baseline", normal), ("faulty_uncorrected", uncorrected), ("operated", row)):
            self.ledgers[name].update(data)
        events = self.sim.events[self._event_index:]
        self._event_index = len(self.sim.events)
        self.store.save_tick(self.run_id, row, self.latest_anomaly, self.latest_source, self._reports(), events,
                             status="running" if self.running else "paused", metadata=self.metadata())

    async def _loop(self):
        try:
            while not self.closed:
                await self.running_event.wait()
                async with self.lock:
                    if self.closed:
                        break
                    if self.running:
                        if self.sim.tick >= self.settings.max_ticks:
                            self._pause("tick_limit_reached")
                        else:
                            await asyncio.to_thread(self._advance)
                try:
                    await asyncio.wait_for(self.changed.wait(), timeout=1 / self.speed)
                except asyncio.TimeoutError:
                    pass
                self.changed.clear()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            async with self.lock:
                self.error = f"{type(error).__name__}: {error}"
                self._pause("runtime_error")

    def _pause(self, reason="simulation_paused"):
        self.running = False
        self.running_event.clear()
        self.changed.set()
        self.store.update_scenario(self.run_id, "paused", self.metadata())
        self.store.event(self.run_id, self.sim.tick, reason)

    async def start(self, speed=None):
        async with self.lock:
            if self.error:
                raise RuntimeConflict("Reset the simulation after a runtime error")
            if self.sim.tick >= self.settings.max_ticks:
                raise RuntimeConflict("Tick limit reached; reset to start a new run")
            was_running = self.running
            speed_changed = speed is not None and speed != self.speed
            if speed is not None:
                self.speed = speed
            if not self.running:
                self.running = True
                self.store.event(self.run_id, self.sim.tick, "simulation_started")
            if self.task is None or self.task.done():
                self.task = asyncio.create_task(self._loop())
            self.running_event.set()
            if not was_running:
                self.changed.clear()
            elif speed_changed:
                self.changed.set()
            self.store.update_scenario(self.run_id, "running", self.metadata())
            return self.state()

    async def pause(self):
        async with self.lock:
            if self.running:
                self._pause()
            return self.state()

    async def set_speed(self, speed):
        async with self.lock:
            self.speed = speed
            self.changed.set()
            return self.state()

    def _archive(self):
        reports = self.tracker.reports()
        for report in reports:
            if report["status"] == "open":
                report.update(status="interrupted", interruption_reason="simulation_reset")
                report["explanation"]["recovery"] = "Simulation reset; recovery was not observed."
        self.store.save_reports(self.run_id, reports)
        self.store.update_scenario(self.run_id, "reset", self.metadata())

    async def reset(self, seed=None, config=None, fault=None):
        async with self.lock:
            if self.running:
                raise RuntimeConflict("Pause before resetting or replacing the scenario")
            config = config or self.sim.config
            seed = self.sim.seed if seed is None else seed
            if fault and fault.start_tick + fault.duration_ticks > self.settings.max_ticks:
                raise ValueError("Fault must finish within the configured run tick limit")
            self._archive()
            self._new_run(config, seed)
            if fault:
                self.sim.faults.schedule(fault)
                self.uncorrected.faults.schedule(fault)
            self.store.update_scenario(self.run_id, "paused", self.metadata())
            return self.state()

    async def inject(self, fault_request):
        async with self.lock:
            fault = fault_request.fault(self.sim.tick)
            if fault.start_tick + fault.duration_ticks > self.settings.max_ticks:
                raise ValueError("Fault must finish within the configured run tick limit")
            # Validate both engines before mutating either schedule.
            for engine in (self.sim.faults, self.uncorrected.faults):
                if fault.start_tick < self.sim.tick or any(
                    max(item["start_tick"], fault.start_tick) < min(item["start_tick"] + item["duration_ticks"], fault.start_tick + fault.duration_ticks)
                    for item in engine.ground_truth() if item["cancelled_at_tick"] is None):
                    raise ValueError("Fault is in the past or overlaps a planned fault in a comparison run")
            self.sim.faults.schedule(fault, self.sim.tick)
            self.uncorrected.faults.schedule(fault, self.sim.tick)
            self.store.event(self.run_id, self.sim.tick, "fault_scheduled", category="simulation_action")
            self.store.update_scenario(self.run_id, "running" if self.running else "paused", self.metadata())
            return {"scheduled": asdict(fault), "label": "Simulated ground truth; not a model prediction"}

    async def correct(self):
        async with self.lock:
            self.sim.correct()
            self.correction_ticks.append(self.sim.tick)
            events = self.sim.events[self._event_index:]
            self._event_index = len(self.sim.events)
            for event in events:
                self.store.event(self.run_id, event["tick"], event["event"])
            self.store.update_scenario(self.run_id, "running" if self.running else "paused", self.metadata())
            return self.state()

    async def step(self, ticks):
        async with self.lock:
            if self.running:
                raise RuntimeConflict("Pause before manually advancing the simulation")
            if self.error:
                raise RuntimeConflict("Reset after a runtime error")
            if self.sim.tick + ticks > self.settings.max_ticks:
                raise RuntimeConflict("Requested steps exceed the run tick limit")
            try:
                for _ in range(ticks):
                    await asyncio.to_thread(self._advance)
            except Exception as error:
                self.error = f"{type(error).__name__}: {error}"
                raise
            self.store.update_scenario(self.run_id, "paused", self.metadata())
            return self.state()

    async def start_evaluation(self, profile):
        async with self.lock:
            if self.evaluation_task and not self.evaluation_task.done():
                raise RuntimeConflict("A model evaluation is already running")
            if not self.models.detector and not self.models.localizer:
                raise LookupError("No trained models are available to evaluate")
            evaluation_id = uuid.uuid4().hex
            self.evaluation = {"id": evaluation_id, "status": "running", "profile": profile}
            self.evaluation_task = asyncio.create_task(self._evaluate(evaluation_id, profile))
            return dict(self.evaluation)

    async def _evaluate(self, evaluation_id, profile):
        try:
            reports = await asyncio.to_thread(self.models.evaluate, profile)
            self.models.reports = reports
            self.store.save_evaluation(evaluation_id, {"artifacts": self.models.fingerprints, "reports": reports})
            self.evaluation = {"id": evaluation_id, "status": "complete", "profile": profile}
        except Exception as error:
            self.evaluation = {"id": evaluation_id, "status": "failed", "profile": profile,
                               "error": f"{type(error).__name__}: {error}"}

    async def close(self):
        async with self.lock:
            self.closed = True
            self.running = False
            reports = self.tracker.reports()
            for report in reports:
                if report["status"] == "open":
                    report.update(status="interrupted", interruption_reason="backend_shutdown")
                    report["explanation"]["recovery"] = "Backend stopped; recovery was not observed."
            self.store.save_reports(self.run_id, reports)
            self.store.update_scenario(self.run_id, "stopped", self.metadata())
            if self.task:
                self.task.cancel()
        if self.task:
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        if self.evaluation_task:
            await self.evaluation_task
        self.store.close()
