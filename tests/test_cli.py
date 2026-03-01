import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def test_cli_check_ok(tmp_path: Path):
    src = tmp_path / "ok.astra"
    src.write_text("fn main() -> Int { return 0; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "check", str(src)])
    assert rc == 0


def test_cli_check_fails_on_semantic_error(tmp_path: Path):
    src = tmp_path / "bad.astra"
    src.write_text('fn main() -> Int { return "x"; }')
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "check", str(src)])
    assert rc != 0


def test_cli_build_emit_ir(tmp_path: Path):
    src = tmp_path / "ok.astra"
    out = tmp_path / "ok.py"
    ir = tmp_path / "ok.ir.json"
    src.write_text("fn main() -> Int { let x = 1 + 2; return x; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "build", str(src), "-o", str(out), "--emit-ir", str(ir)])
    assert rc == 0
    assert out.exists()
    assert ir.exists()


def test_cli_build_accepts_profile_and_overflow_flags(tmp_path: Path):
    src = tmp_path / "ok.astra"
    out = tmp_path / "ok.py"
    src.write_text("fn main() -> Int { return 0; }")
    rc = subprocess.call(
        [
            sys.executable,
            "-m",
            "astra.cli",
            "build",
            str(src),
            "-o",
            str(out),
            "--profile",
            "release",
            "--overflow",
            "wrap",
        ]
    )
    assert rc == 0
    assert out.exists()


def test_cli_check_freestanding_without_main(tmp_path: Path):
    src = tmp_path / "k.astra"
    src.write_text("fn kernel() -> Int { return 0; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "check", str(src), "--freestanding"])
    assert rc == 0


def test_cli_check_accepts_overflow_flag(tmp_path: Path):
    src = tmp_path / "ok.astra"
    src.write_text("fn main() -> Int { return 0; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "check", str(src), "--overflow", "debug"])
    assert rc == 0


def test_cli_build_freestanding_x86(tmp_path: Path):
    src = tmp_path / "boot.astra"
    out = tmp_path / "boot.s"
    src.write_text("fn _start() -> Int { return 0; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "build", str(src), "-o", str(out), "--target", "x86_64", "--freestanding"])
    assert rc == 0
    asm = out.read_text()
    assert "global _start" in asm
    assert "_start:" in asm


@pytest.mark.skipif(
    shutil.which("nasm") is None or (shutil.which("cc") is None and shutil.which("ld") is None),
    reason="native target requires nasm and a linker (cc/ld)",
)
def test_cli_build_native_executable(tmp_path: Path):
    src = tmp_path / "ok.astra"
    out = tmp_path / "ok.exe"
    src.write_text("fn main() -> Int { return 11; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "build", str(src), "-o", str(out), "--target", "native"])
    assert rc == 0
    assert out.exists()
    assert out.stat().st_mode & 0o111
    rc = subprocess.call([str(out)])
    assert rc == 11
