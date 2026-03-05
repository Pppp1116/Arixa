import json
import os
import subprocess
import sys
from pathlib import Path


def test_pkg_init_add_lock(tmp_path: Path):
    root = Path(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    rc = subprocess.call([sys.executable, "-m", "astra.pkg", "init", "demo"], cwd=root, env=env)
    assert rc == 0
    rc = subprocess.call([sys.executable, "-m", "astra.pkg", "add", "foo", "1.2.3"], cwd=root, env=env)
    assert rc == 0
    rc = subprocess.call([sys.executable, "-m", "astra.pkg", "lock"], cwd=root, env=env)
    assert rc == 0
    manifest = (root / "Astra.toml").read_text()
    lock = json.loads((root / "Astra.lock").read_text())
    assert 'name = "demo"' in manifest
    assert lock["version"] == 1
    assert lock["packages"]["foo"]["version"] == "1.2.3"
    assert lock["packages"]["foo"]["constraint"] == "1.2.3"


def test_pkg_new_scaffolds_project(tmp_path: Path):
    root = Path(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    rc = subprocess.call([sys.executable, "-m", "astra.pkg", "new", "hello"], cwd=root, env=env)
    assert rc == 0
    manifest = (root / "hello" / "Astra.toml").read_text()
    main_src = (root / "hello" / "src" / "main.astra").read_text()
    assert '[project]' in manifest
    assert 'name = "hello"' in manifest
    assert 'entry = "src/main.astra"' in manifest
    assert 'fn main() -> Int {' in main_src
