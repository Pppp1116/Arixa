import subprocess
import sys
from pathlib import Path


def test_bundled_stdlib_matches_repo_stdlib():
    repo_stdlib = Path("stdlib")
    bundled_stdlib = Path("astra/stdlib")
    repo_files = sorted(p.name for p in repo_stdlib.glob("*.astra"))
    bundled_files = sorted(p.name for p in bundled_stdlib.glob("*.astra"))
    assert bundled_files == repo_files
    for name in repo_files:
        assert (bundled_stdlib / name).read_text() == (repo_stdlib / name).read_text()


def test_bundled_runtime_matches_repo_runtime():
    repo_runtime = Path("runtime/llvm_runtime.c")
    bundled_runtime = Path("astra/assets/runtime/llvm_runtime.c")
    assert bundled_runtime.read_text() == repo_runtime.read_text()


def test_runtime_sync_script_keeps_bundled_runtime_in_sync():
    rc = subprocess.call([sys.executable, "scripts/sync_runtime_asset.py"])
    assert rc == 0
    repo_runtime = Path("runtime/llvm_runtime.c")
    bundled_runtime = Path("astra/assets/runtime/llvm_runtime.c")
    assert bundled_runtime.read_text() == repo_runtime.read_text()
