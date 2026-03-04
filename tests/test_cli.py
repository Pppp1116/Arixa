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
    ir = tmp_path / "ok.ll"
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


def test_cli_build_freestanding_llvm(tmp_path: Path):
    src = tmp_path / "boot.astra"
    out = tmp_path / "boot.ll"
    src.write_text("fn _start() -> Int { return 0; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "build", str(src), "-o", str(out), "--target", "llvm", "--freestanding"])
    assert rc == 0
    mod = out.read_text()
    assert "define i64 @_start()" in mod


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
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


def test_cli_build_accepts_triple_for_llvm(tmp_path: Path):
    src = tmp_path / "ok.astra"
    out = tmp_path / "ok.ll"
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
            "--target",
            "llvm",
            "--triple",
            "wasm32-unknown-unknown",
        ]
    )
    assert rc == 0
    assert "target triple = \"wasm32-unknown-unknown\"" in out.read_text()


def test_cli_selfhost_is_honestly_labeled_unavailable():
    proc = subprocess.run(
        [sys.executable, "-m", "astra.cli", "selfhost"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "selfhost-unavailable" in proc.stderr


def test_cli_check_stdin_json_reports_stable_codes():
    proc = subprocess.run(
        [sys.executable, "-m", "astra.cli", "check", "--stdin", "--stdin-filename", "<mem>", "--json"],
        input='fn main() -> Int { return "x"; }',
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert '"code": "ASTRA-TYPE-0001"' in proc.stdout


def test_cli_check_files_mode_reports_errors(tmp_path: Path):
    ok = tmp_path / "ok.astra"
    bad = tmp_path / "bad.astra"
    ok.write_text("fn main() -> Int { return 0; }")
    bad.write_text('fn main() -> Int { return "x"; }')
    proc = subprocess.run(
        [sys.executable, "-m", "astra.cli", "check", "--files", str(ok), str(bad)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "ASTRA-TYPE-0001" in proc.stderr


def test_cli_fmt_and_doc_subcommands(tmp_path: Path):
    src = tmp_path / "a.astra"
    out = tmp_path / "api.md"
    src.write_text("fn main() -> Int {\nprint(1);\nreturn 0;\n}\n")
    rc_fmt = subprocess.call([sys.executable, "-m", "astra.cli", "fmt", str(src)])
    assert rc_fmt == 0
    rc_fmt_check = subprocess.call([sys.executable, "-m", "astra.cli", "fmt", str(src), "--check"])
    assert rc_fmt_check == 0
    rc_doc = subprocess.call([sys.executable, "-m", "astra.cli", "doc", str(src), "-o", str(out)])
    assert rc_doc == 0
    assert out.exists()


def test_cli_build_accepts_opt_size_flag(tmp_path: Path):
    src = tmp_path / "ok.astra"
    out = tmp_path / "ok.py"
    src.write_text("fn main() -> Int { return 0; }")
    rc = subprocess.call([sys.executable, "-m", "astra.cli", "build", str(src), "-o", str(out), "--opt-size"])
    assert rc == 0
    assert out.exists()
