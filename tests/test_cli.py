import subprocess
import sys
from pathlib import Path


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


def test_cli_check_freestanding_without_main(tmp_path: Path):
    src = tmp_path / "k.astra"
    src.write_text("fn kernel() -> Int { return 0; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "check", str(src), "--freestanding"])
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
