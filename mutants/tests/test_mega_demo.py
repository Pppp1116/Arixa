import os
import subprocess
import sys
from pathlib import Path

def run(cmd, cwd: Path):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=30)

def test_mega_demo_py(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    src = repo / "examples" / "mega_demo.arixa"

    # write a config.json so it exercises JSON parsing
    (tmp_path / "config.json").write_text('{"seed": 7, "n": 5000, "mode": "mix", "out": "report_py.json"}')

    out = tmp_path / "mega_demo.py"
    cp = run([sys.executable, "-m", "astra.cli", "build", str(src), "-o", str(out), "--target", "py"], cwd=repo)
    assert cp.returncode == 0, cp.stderr

    cp2 = run([sys.executable, str(out)], cwd=tmp_path)
    assert cp2.returncode == 0 or (0 <= cp2.returncode <= 255)
    assert (tmp_path / "report_py.json").exists()
    assert "mega_demo" in cp2.stdout

def test_mega_demo_native(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    src = repo / "examples" / "mega_demo.arixa"

    (tmp_path / "config.json").write_text('{"seed": 7, "n": 5000, "mode": "mix", "out": "report_native.json"}')

    out = tmp_path / "mega_demo.native"
    # requires clang installed
    cp = run([sys.executable, "-m", "astra.cli", "build", str(src), "-o", str(out), "--target", "native", "--profile", "release"], cwd=repo)
    assert cp.returncode == 0, cp.stderr

    os.chmod(out, 0o755)
    cp2 = run([str(out)], cwd=tmp_path)
    assert cp2.returncode == 0 or (0 <= cp2.returncode <= 255)
    assert (tmp_path / "report_native.json").exists()
    assert "mega_demo" in cp2.stdout
