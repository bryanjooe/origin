"""Managed, append-only JSONL and JSON artifact storage for run outputs."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile


@dataclass(frozen=True)
class Artifact:
    relative_path: str
    sha256: str
    size_bytes: int


class FileArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def _write(self, relative_path: str, content: bytes) -> Artifact:
        destination = self._resolve(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_path = tempfile.mkstemp(prefix=".pending-", dir=destination.parent)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, destination)
        except Exception:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
            raise
        return Artifact(relative_path, hashlib.sha256(content).hexdigest(), len(content))

    def write_json(self, relative_path: str, value: object) -> Artifact:
        content = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return self._write(relative_path, content)

    def write_telemetry_chunk(
        self, run_id: str, start_tick: int, end_tick: int, rows: list[dict]
    ) -> Artifact:
        relative = f"runs/{run_id}/telemetry-{start_tick:06d}-{end_tick:06d}.jsonl"
        content = b"".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            + b"\n"
            for row in rows
        )
        return self._write(relative, content)

    def read_telemetry_chunks(
        self, chunks: list[dict], start_tick: int, end_tick: int
    ) -> list[dict]:
        rows = []
        for chunk in chunks:
            path = self._resolve(chunk["relative_path"])
            with path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    row = json.loads(line)
                    if start_tick <= row["tick"] < end_tick:
                        rows.append(row)
        rows.sort(key=lambda row: row["tick"])
        return rows

    def delete(self, relative_path: str) -> None:
        try:
            self._resolve(relative_path).unlink(missing_ok=True)
        except FileNotFoundError:
            pass

    def _resolve(self, relative_path: str) -> Path:
        candidate = PurePosixPath(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError("Artifact path is invalid")
        resolved = (self.root / Path(*candidate.parts)).resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError("Artifact path is outside the configured data directory")
        return resolved
