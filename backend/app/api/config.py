from dataclasses import dataclass
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


@dataclass
class ServerSettings:
    database_path: Path | str = ROOT / "outputs/server/greengrid.sqlite3"
    anomaly_model: Path | None = ROOT / "outputs/stage2/anomaly.joblib"
    source_model: Path | None = ROOT / "outputs/stage3/source_classifier.joblib"
    max_ticks: int = 10000

    @classmethod
    def from_environment(cls):
        def path(name, default):
            legacy_name = name.replace("ORIGIN_", "TRACEX_")
            value = os.environ.get(name, os.environ.get(legacy_name, str(default)))
            return Path(value) if value else None
        return cls(database_path=os.environ.get(
                       "ORIGIN_DATABASE", os.environ.get("TRACEX_DATABASE", str(cls.database_path))),
                   anomaly_model=path("ORIGIN_ANOMALY_MODEL", cls.anomaly_model),
                   source_model=path("ORIGIN_SOURCE_MODEL", cls.source_model))
