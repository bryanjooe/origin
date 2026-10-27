"""Single-process, bounded in-memory jobs; automatic mode is opt-in per lifetime."""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from uuid import uuid4

from app.api.runtime import RuntimeConflict
from app.database.store import utc_now
from .context import observable_context
from .planner import PlanningBudget, plan_investigation
from .orchestrator import SnapshotReference, run_autonomous_investigation


class InvestigationManager:
    def __init__(self, runtime, gate, *, retention=20):
        self.runtime, self.gate = runtime, gate
        self.loop = asyncio.get_running_loop()
        self.enabled = self.closed = False
        self.retention = retention
        self.jobs = OrderedDict()
        self.active_id = None
        self.task = None
        self.auto_seen = set()
        self.auto_skips = set()
        self.enabled_since = (runtime.run_id, runtime.sim.tick)
        self.manual_seen = OrderedDict()
        self.seen_run = runtime.run_id
        runtime.incident_listener = self.observe_new_incidents

    @property
    def busy(self):
        return self.active_id is not None

    def _sync_run(self):
        if self.seen_run != self.runtime.run_id:
            self.seen_run = self.runtime.run_id
            self.auto_seen.clear()
            self.auto_skips.clear()
            self.manual_seen.clear()

    @staticmethod
    def _bounded_incident(incident):
        if incident is None: return None
        # Match the existing ShadowTwin evidence bound without changing durable
        # history or rejecting a long historical reference outright.
        records=incident.get("evidence", [])
        return {**incident,"evidence":records[-256:] if isinstance(records,list) else []}

    def _new_job(self, trigger, run_id, incident_id, tick, status="investigating", reason=None):
        ident = "agent-" + uuid4().hex
        job = {"id":ident,"trigger":trigger,"run_id":run_id,"incident_id":incident_id,
            "snapshot_tick":tick,"status":status,"stage":"capturing_snapshot" if status=="investigating" else status,
            "created_at":utc_now(),"finished_at":None,"completed_experiments":0,
            "events":[],"progress_steps":[],"report":None,"error":None,"reason":reason,
            "evidence_projection":"At most 256 latest recorded residuals enter the approved context; full incident history remains in the incident API."}
        self.jobs[ident] = job
        while len(self.jobs)>self.retention:
            oldest = next((key for key in self.jobs if key != self.active_id and key != ident), None)
            if oldest is None: break
            self.jobs.pop(oldest)
        return job

    def _view(self, job, detail=False):
        stale = job["run_id"] != self.runtime.run_id
        value = {key:deepcopy(item) for key,item in job.items() if detail or key not in ("report","progress_steps","events")}
        value.update(stale=stale,current_run_id=self.runtime.run_id,report_available=job["report"] is not None)
        if stale and job["status"] != "investigating": value["status"]="stale"
        return value

    def status(self):
        self._sync_run()
        recent=[self._view(job) for job in reversed(self.jobs.values())]
        active=self._view(self.jobs[self.active_id]) if self.active_id else None
        latest=next((job for job in recent if not job["stale"] and job["status"] != "investigating"),None)
        return {"automatic_enabled":self.enabled,"current_run_id":self.runtime.run_id,
            "active":active,"latest":latest,"recent":recent,"retention":self.retention,
            "lifecycle":"Single backend process; automatic mode resets OFF and reports expire on restart. Disabling prevents new jobs; active isolated work completes safely."}

    def get(self, ident):
        if ident not in self.jobs: raise KeyError(ident)
        return self._view(self.jobs[ident],True)

    def configure(self, enabled):
        if self.closed: raise RuntimeConflict("Agent is shutting down")
        if enabled and not self.enabled:
            self.enabled_since=(self.runtime.run_id,self.runtime.sim.tick)
        self.enabled=enabled
        return self.status()

    def observe_new_incidents(self, reports):
        """Called after incident changes are persisted, under the existing runtime lock.

        This thread captures approved observations and detached state only. All
        coordination/storage changes happen back on the owning event loop.
        """
        if not self.enabled or self.closed: return
        for local in reports:
            run_id=self.runtime.run_id
            incident_id=f"{run_id}:{local['id']}"
            key=(run_id,incident_id)
            enabled_tick=self.enabled_since[1] if self.enabled_since[0]==run_id else 0
            if key in self.auto_seen or local.get("status") != "open" or local.get("as_of_tick") != self.runtime.sim.tick-1 or local.get("detection_tick",-1)<enabled_tick:
                continue
            if self.busy or self.gate.locked():
                self.loop.call_soon_threadsafe(self._receive_auto,run_id,incident_id,self.runtime.sim.tick,None,None,"Another investigation is active; no pending work was queued.")
                continue
            try:
                incident=self._bounded_incident({**local,"id":incident_id,"run_id":run_id})
                context=observable_context(self.runtime.state(),incident)
                preview=plan_investigation(context,budget=PlanningBudget(max_experiments=3))
                if preview["status"] != "ready":
                    self.loop.call_soon_threadsafe(self._receive_auto,run_id,incident_id,context.current_tick,None,None,preview["reason"])
                    continue
                snapshot=self.runtime._shadow_snapshot_locked()
                reference=SnapshotReference(snapshot,run_id,f"{run_id}:{snapshot.next_tick}")
                self.loop.call_soon_threadsafe(self._receive_auto,run_id,incident_id,context.current_tick,context,reference,None)
            except Exception as error:
                # Optional investigation must never stop the live simulator.
                self.loop.call_soon_threadsafe(self._receive_auto,run_id,incident_id,self.runtime.sim.tick,None,None,f"Investigation preparation failed ({type(error).__name__}); no work started.")

    def _receive_auto(self, run_id, incident_id, tick, context, reference, reason):
        self._sync_run()
        key=(run_id,incident_id)
        if self.closed or not self.enabled or run_id != self.runtime.run_id or key in self.auto_seen: return
        if self.busy or self.gate.locked():
            reason="Another investigation is active; no pending work was queued."
            self.auto_seen.add(key)
        if reason:
            if reason.startswith("Another investigation"):
                self.auto_seen.add(key)
            if key in self.auto_skips: return
            self.auto_skips.add(key)
            job=self._new_job("automatic",run_id,incident_id,tick,"skipped",reason)
            job["finished_at"]=utc_now()
            return
        self.auto_seen.add(key)
        job=self._new_job("automatic",run_id,incident_id,tick)
        self.active_id=job["id"]
        self.task=asyncio.create_task(self._execute(job,context,reference,PlanningBudget(max_experiments=3)))

    async def start(self, incident_id, expected_run_id, budget):
        self._sync_run()
        if self.closed: raise RuntimeConflict("Agent is shutting down")
        if self.busy or self.gate.locked(): raise RuntimeConflict("A virtual investigation is already running")
        # Reserve synchronously before awaiting the runtime lock. The manual
        # ShadowTwin endpoint checks this reservation as well as its shared gate.
        job=self._new_job("manual",expected_run_id,incident_id,None)
        self.active_id=job["id"]
        try:
            async with self.runtime.lock:
                if self.closed: raise RuntimeConflict("Agent is shutting down")
                if expected_run_id != self.runtime.run_id: raise RuntimeConflict("Simulation run changed; refresh before starting an investigation")
                incident=self.runtime.store.incident(incident_id) if incident_id is not None else None
                if incident_id is not None and incident is None: raise KeyError(incident_id)
                context=observable_context(self.runtime.state(),self._bounded_incident(incident))
                key=(expected_run_id,incident_id,context.current_tick)
                if key in self.manual_seen:
                    previous=self.manual_seen[key]
                    self.jobs.pop(job["id"],None);self.active_id=None
                    if previous not in self.jobs: raise RuntimeConflict("An identical captured-state investigation already completed; its report has expired")
                    return self.get(previous)
                if len(self.manual_seen)>=10000: raise RuntimeConflict("Per-run investigation limit reached; reset the simulation before starting more")
                snapshot=self.runtime._shadow_snapshot_locked()
                reference=SnapshotReference(snapshot,expected_run_id,f"{expected_run_id}:{snapshot.next_tick}")
                job["snapshot_tick"]=context.current_tick
                self.manual_seen[key]=job["id"]
            self.task=asyncio.create_task(self._execute(job,context,reference,budget))
            return self.get(job["id"])
        except BaseException:
            self.jobs.pop(job["id"],None)
            if self.active_id==job["id"]: self.active_id=None
            raise

    def _progress(self, ident, event):
        job=self.jobs.get(ident)
        if job is None or job["status"] != "investigating": return
        job["stage"]=event["stage"]
        job["events"].append({key:deepcopy(value) for key,value in event.items() if key != "completed_step"})
        job["events"]=job["events"][-24:]
        if "completed_step" in event:
            job["progress_steps"].append(deepcopy(event["completed_step"]))
            job["completed_experiments"]=sum(step["execution_status"]=="completed" for step in job["progress_steps"])

    async def _execute(self, job, context, reference, budget):
        try:
            async with self.gate:
                callback=lambda event:self.loop.call_soon_threadsafe(self._progress,job["id"],event)
                work=asyncio.create_task(asyncio.to_thread(run_autonomous_investigation,context,reference,budget,progress=callback))
                try:
                    report=await asyncio.shield(work)
                except asyncio.CancelledError:
                    report=await work  # Never release the guard while its worker survives.
                job.update(report=report,status=report["status"],stage="finished",completed_experiments=report["executed_experiments"],progress_steps=report["steps"])
        except Exception as error:
            job.update(status="failed",stage="failed",error=f"Investigation failed ({type(error).__name__}); inspect backend logs.")
        finally:
            job["finished_at"]=utc_now()
            if self.active_id==job["id"]: self.active_id=None

    async def close(self):
        self.closed=True
        self.enabled=False
        self.runtime.incident_listener=None
        if self.task: await self.task
