from pathlib import Path
import tempfile

import pytest


@pytest.fixture
def workspace_tmp_path():
    parent = Path(__file__).resolve().parents[2] / "outputs" / "test-temp"
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=parent) as directory:
        yield Path(directory)
