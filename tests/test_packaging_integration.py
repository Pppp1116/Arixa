import subprocess
import sys
from pathlib import Path


def test_integration_editable_install_and_entrypoints(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    venv = tmp_path / "venv"
    assert subprocess.call([sys.executable, "-m", "venv", str(venv)]) == 0
    py = venv / "bin" / "python"
    pip = venv / "bin" / "pip"
    astra = venv / "bin" / "astra"
    assert subprocess.call([str(pip), "install", "-q", "-e", str(repo)]) == 0
    assert subprocess.call([str(py), "-m", "astra", "--help"]) == 0
    assert subprocess.call([str(astra), "--help"]) == 0
