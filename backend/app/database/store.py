"""SQLite history. Tick telemetry, evidence snapshots and events commit together."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from threading import RLock


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, allow_nan=False, separators=(",", ":"))


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.connection = sqlite3.connect(str(path), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                status TEXT NOT NULL, metadata TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS telemetry (
                run_id TEXT NOT NULL REFERENCES scenarios(id), tick INTEGER NOT NULL,
                payload TEXT NOT NULL, anomaly TEXT, source TEXT, PRIMARY KEY(run_id,tick));
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES scenarios(id),
                created_at TEXT NOT NULL, severity TEXT NOT NULL, status TEXT NOT NULL,
                source TEXT NOT NULL, report TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS incidents_run ON incidents(run_id);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL REFERENCES scenarios(id),
                tick INTEGER NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
        """)
        self.connection.commit()

    def recover_interrupted(self):
        with self.lock, self.connection:
            self.connection.execute("UPDATE scenarios SET status='interrupted',updated_at=? WHERE status IN ('running','paused')", (utc_now(),))
            for row in self.connection.execute("SELECT id,report FROM incidents").fetchall():
                report = json.loads(row["report"])
                interrupted = report["status"] == "open"
                pending = (report.get("security_attribution") or {}).get("status") == "pending"
                if not interrupted and not pending:
                    continue
                if interrupted:
                    report.update(status="interrupted", interruption_reason="backend_restart")
                    report["explanation"]["recovery"] = "Backend restarted; recovery was not observed."
                if pending:
                    report["security_attribution"].update(status="insufficient_evidence",
                        reason="Backend restarted before the observed classification window completed.")
                self.connection.execute("UPDATE incidents SET status=?,report=? WHERE id=?",
                                        (report["status"], encode(report), row["id"]))

    def create_scenario(self, run_id, metadata):
        now = utc_now()
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO scenarios VALUES (?,?,?,?,?)", (run_id, now, now, "paused", encode(metadata)))

    def update_scenario(self, run_id, status, metadata):
        with self.lock, self.connection:
            self.connection.execute("UPDATE scenarios SET status=?,metadata=?,updated_at=? WHERE id=?",
                                    (status, encode(metadata), utc_now(), run_id))

    def _save_reports(self, run_id, reports):
        for original in reports:
            report = {**original, "local_id": original["id"], "id": f"{run_id}:{original['id']}", "run_id": run_id}
            self.connection.execute("""INSERT INTO incidents VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET severity=excluded.severity,status=excluded.status,
                source=excluded.source,report=excluded.report""",
                (report["id"], run_id, utc_now(), report["severity"], report["status"],
                 report["diagnosis"]["source"], encode(report)))

    def save_reports(self, run_id, reports):
        with self.lock, self.connection:
            self._save_reports(run_id, reports)

    def save_tick(self, run_id, row, anomaly, source, reports, events, *, status=None, metadata=None):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO telemetry VALUES (?,?,?,?,?)", (
                run_id, row["tick"], encode(row), encode(anomaly) if anomaly else None, encode(source) if source else None))
            self._save_reports(run_id, reports)
            for event in events:
                self.connection.execute("INSERT INTO events(run_id,tick,created_at,payload) VALUES (?,?,?,?)",
                                        (run_id, event["tick"], utc_now(), encode(event)))
            if metadata is not None:
                self.connection.execute("UPDATE scenarios SET status=?,metadata=?,updated_at=? WHERE id=?",
                                        (status, encode(metadata), utc_now(), run_id))

    def event(self, run_id, tick, event, **details):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO events(run_id,tick,created_at,payload) VALUES (?,?,?,?)",
                                    (run_id, tick, utc_now(), encode({"tick": tick, "event": event, **details})))

    def scenarios(self, limit=100):
        with self.lock:
            return [{**dict(row), "metadata": json.loads(row["metadata"])} for row in self.connection.execute(
                "SELECT * FROM scenarios ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()]

    def scenario(self, run_id):
        with self.lock:
            row = self.connection.execute("SELECT * FROM scenarios WHERE id=?", (run_id,)).fetchone()
            return {**dict(row), "metadata": json.loads(row["metadata"])} if row else None

    def telemetry(self, run_id, after=-1, limit=300):
        with self.lock:
            rows = self.connection.execute("SELECT * FROM telemetry WHERE run_id=? AND tick>? ORDER BY tick LIMIT ?",
                                           (run_id, after, limit)).fetchall()
            return [{"telemetry": json.loads(row["payload"]),
                     "anomaly": json.loads(row["anomaly"]) if row["anomaly"] else None,
                     "source": json.loads(row["source"]) if row["source"] else None} for row in rows]

    def incidents(self, *, run_id=None, severity=None, status=None, source=None, search="", limit=100, offset=0):
        clauses, params = [], []
        for column, value in (("run_id", run_id), ("severity", severity), ("status", status), ("source", source)):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        if search:
            clauses.append("(id LIKE ? OR source LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.lock:
            total = self.connection.execute("SELECT count(*) FROM incidents" + where, params).fetchone()[0]
            rows = self.connection.execute("SELECT * FROM incidents" + where + " ORDER BY created_at DESC LIMIT ? OFFSET ?",
                                           [*params, limit, offset]).fetchall()
            items = []
            for row in rows:
                report = json.loads(row["report"])
                items.append({key: report[key] for key in ("id", "run_id", "local_id", "status", "severity",
                             "detection_tick", "detection_time_seconds", "diagnosis", "confirmation_delay_seconds", "as_of_tick")}
                             | {"created_at": row["created_at"],
                                "security_attribution": report.get("security_attribution")})
            return {"items": items, "total": total, "limit": limit, "offset": offset}

    def incident(self, incident_id):
        with self.lock:
            row = self.connection.execute("SELECT report,created_at FROM incidents WHERE id=?", (incident_id,)).fetchone()
            return {**json.loads(row["report"]), "created_at": row["created_at"]} if row else None

    def save_security_assessment(self, incident_id, assessment):
        """Enrich legacy JSON reports without replacing their diagnosis or schema."""
        with self.lock, self.connection:
            row = self.connection.execute("SELECT report FROM incidents WHERE id=?", (incident_id,)).fetchone()
            if row is not None:
                report = json.loads(row["report"])
                report["security_attribution"] = assessment
                self.connection.execute("UPDATE incidents SET report=? WHERE id=?", (encode(report), incident_id))

    def events(self, run_id=None, after=0, limit=100):
        with self.lock:
            query = "SELECT * FROM events WHERE id>?" + (" AND run_id=?" if run_id else "") + " ORDER BY id LIMIT ?"
            params = [after, run_id, limit] if run_id else [after, limit]
            return [{"id": row["id"], "run_id": row["run_id"], "created_at": row["created_at"], **json.loads(row["payload"])}
                    for row in self.connection.execute(query, params).fetchall()]

    def save_evaluation(self, evaluation_id, payload):
        with self.lock, self.connection:
            self.connection.execute("INSERT INTO evaluations VALUES (?,?,?)", (evaluation_id, utc_now(), encode(payload)))

    def latest_evaluation(self):
        with self.lock:
            row = self.connection.execute("SELECT payload FROM evaluations ORDER BY created_at DESC LIMIT 1").fetchone()
            return json.loads(row[0]) if row else None

    def close(self):
        self.connection.close()
