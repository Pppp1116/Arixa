"""Comprehensive codegen tests aligned with current backend contracts."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from astra.build import build
from astra.codegen import to_python
from astra.llvm_codegen import to_llvm_ir
from astra.parser import parse
from astra.semantic import analyze


def _analyzed(src: str):
    return analyze(parse(src))


def test_python_codegen_emits_main_function() -> None:
    py = to_python(_analyzed("fn main() Int{ return 42; }"))
    assert "def main():" in py
    assert "return 42" in py
    assert "if __name__ == '__main__':" in py


def test_python_codegen_control_flow() -> None:
    src = "fn main() Int{ mut x = 0; while x < 3 { x += 1; } if x == 3 { return 1; } else { return 0; } }"
    py = to_python(_analyzed(src))
    assert "while (x < 3):" in py or "while x < 3:" in py
    assert "if (x == 3):" in py or "if x == 3:" in py


def test_python_codegen_for_range_loop() -> None:
    src = "fn main() Int{ mut s = 0; for i in 1..=3 { s += i; } return s; }"
    py = to_python(_analyzed(src))
    assert "for i in range(1, (3) + 1):" in py or "for i in range(1, 3 + 1):" in py


def test_python_codegen_match_lowering() -> None:
    src = "fn main() Int{ x = 1; match x { 0 => { return 0; }, _ => { return 1; } } return 0; }"
    py = to_python(_analyzed(src))
    assert "__match_value" in py
    assert "__match_done" in py


def test_llvm_codegen_emits_user_main_and_entry() -> None:
    ir = to_llvm_ir(_analyzed("fn main() Int{ return 42; }"))
    assert "define i64 @__astra_user_main()" in ir
    assert "define i32 @main()" in ir


def test_llvm_codegen_handles_struct_field_access() -> None:
    src = "struct Point { x Int, y Int } fn main() Int{ p = Point(2, 3); return p.x + p.y; }"
    ir = to_llvm_ir(_analyzed(src))
    assert "getelementptr" in ir
    assert "define i64 @__astra_user_main()" in ir


def test_gpu_python_codegen_registers_kernel_metadata() -> None:
    src = "gpu fn k(xs GpuSlice<Float>, out GpuMutSlice<Float>) Void{ i = gpu.global_id(); if i < out.len() { out[i] = xs[i]; } else {} } fn main() Int{ return 0; }"
    py = to_python(_analyzed(src))
    assert "register_kernel" in py
    assert "__astra_cuda_kernel_k" in py


def test_build_python_end_to_end(tmp_path: Path) -> None:
    src = tmp_path / "prog.arixa"
    out = tmp_path / "prog.py"
    src.write_text("fn main() Int{ return 7; }")
    assert build(str(src), str(out), target="py") in {"built", "cached"}
    run = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=5)
    assert run.returncode == 7


def test_build_llvm_writes_ir_file(tmp_path: Path) -> None:
    src = tmp_path / "prog.arixa"
    out = tmp_path / "prog.ll"
    src.write_text("fn main() Int{ return 0; }")
    assert build(str(src), str(out), target="llvm") in {"built", "cached"}
    text = out.read_text()
    assert "define i64 @__astra_user_main()" in text


@pytest.mark.skipif(shutil.which("clang") is None, reason="native target requires clang")
def test_build_native_runs(tmp_path: Path) -> None:
    src = tmp_path / "prog.arixa"
    out = tmp_path / "prog.exe"
    src.write_text("fn main() Int{ return 11; }")
    assert build(str(src), str(out), target="native") in {"built", "cached"}
    run = subprocess.run([str(out)], capture_output=True, text=True, timeout=5)
    assert run.returncode == 11
