import subprocess
import sys
from pathlib import Path


def test_integration_editable_install_and_entrypoints(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    venv = tmp_path / "venv"
    assert subprocess.call([sys.executable, "-m", "venv", str(venv)]) == 0
    py = venv / "bin" / "python"
    pip = venv / "bin" / "pip"
    arixa = venv / "bin" / "arixa"
    assert subprocess.call([str(pip), "install", "-q", "-e", str(repo)]) == 0
    assert subprocess.call([str(py), "-m", "astra", "--help"]) == 0
    assert subprocess.call([str(arixa), "--help"]) == 0


def test_integration_wheel_install_has_bundled_stdlib(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    venv = tmp_path / "venv"
    src = tmp_path / "main.astra"
    src.write_text("import std.core; fn main() Int{ return 0; }\n")
    assert subprocess.call([sys.executable, "-m", "venv", str(venv)]) == 0
    pip = venv / "bin" / "pip"
    arixa = venv / "bin" / "arixa"
    assert subprocess.call([str(pip), "install", "-q", str(repo)]) == 0
    assert subprocess.call([str(arixa), "check", str(src)]) == 0
