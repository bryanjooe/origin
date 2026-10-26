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
            value = os.environ.get(name, str(default))
            return Path(value) if value else None
        return cls(database_path=os.environ.get("TRACEX_DATABASE", str(cls.database_path)),
                   anomaly_model=path("TRACEX_ANOMALY_MODEL", cls.anomaly_model),
                   source_model=path("TRACEX_SOURCE_MODEL", cls.source_model))
