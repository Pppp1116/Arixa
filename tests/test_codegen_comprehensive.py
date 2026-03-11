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


def test_python_codegen_supports_builtin_aliases() -> None:
    src = "fn main() Int{ __print(1); s = __format(22); return len(s); }"
    py = to_python(_analyzed(src))
    assert "print_(1)" in py
    assert "format_(22)" in py
    assert "len_(s)" in py


def test_python_codegen_if_expression_emits_ternary() -> None:
    src = "fn main() Int{ x = if true { 1 } else { 2 }; return x; }"
    py = to_python(_analyzed(src))
    assert "if True else" in py


def test_python_codegen_if_expression_without_else_returns_none() -> None:
    src = "fn main() Void{ (if true { 1 }); return; }"
    py = to_python(_analyzed(src))
    assert "if True else None" in py


def test_python_codegen_assertions_and_assume_follow_profile() -> None:
    src = "fn main() Int{ assert(true); debug_assert(true); assume(true); x = likely(true); y = unlikely(false); if x && !y { return 0; } return 1; }"
    py_debug = to_python(_analyzed(src), profile="debug")
    assert "_ASTRA_PROFILE = 'debug'" in py_debug
    assert "assert_(True)" in py_debug
    assert "debug_assert_(True)" in py_debug
    assert "assume_(True)" in py_debug
    assert "likely_(True)" in py_debug
    assert "unlikely_(False)" in py_debug

    py_release = to_python(_analyzed(src), profile="release")
    assert "_ASTRA_PROFILE = 'release'" in py_release
    assert "assert_(True)" in py_release
    assert "debug_assert_(True)" not in py_release
    assert "assume_(True)" in py_release
    assert "likely_(True)" in py_release
    assert "unlikely_(False)" in py_release


def test_python_codegen_unreachable_statement() -> None:
    py = to_python(_analyzed("fn main() Int{ unreachable; }"), profile="debug")
    assert "__astra_unreachable()" in py


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


def test_llvm_codegen_match_int_literals_use_switch() -> None:
    src = """
fn main() Int{
  x = 2;
  match x {
    1 => { return 10; }
    2 => { return 20; }
    3 => { return 30; }
    _ => { return 0; }
  }
  return 0;
}
"""
    ir = to_llvm_ir(_analyzed(src))
    assert "switch i64" in ir


def test_llvm_codegen_ephemeral_array_index_avoids_heap_alloc() -> None:
    src = "fn main() Int{ return [10, 20, 30][1]; }"
    ir = to_llvm_ir(_analyzed(src))
    assert "call i64 @astra_alloc(" not in ir


def test_llvm_codegen_non_escaping_struct_let_promotes_to_stack() -> None:
    src = """
struct Pair { a Int, b Int }
fn main() Int{
  p = Pair(4, 6);
  return p.a + p.b;
}
"""
    ir = to_llvm_ir(_analyzed(src))
    assert "call i64 @astra_alloc(" not in ir


def test_llvm_codegen_assume_uses_intrinsic_in_release() -> None:
    src = "fn main() Int{ x = 1; assume(x > 0); return x; }"
    ir_debug = to_llvm_ir(_analyzed(src), profile="debug")
    ir_release = to_llvm_ir(_analyzed(src), profile="release")
    assert "llvm.assume" not in ir_debug
    assert "call void @llvm.assume(i1" in ir_release


def test_llvm_codegen_assert_and_unreachable_emit_traps_in_debug() -> None:
    assert_ir = to_llvm_ir(_analyzed("fn main() Int{ assert(true); return 0; }"), profile="debug")
    unreachable_ir = to_llvm_ir(_analyzed("fn main() Int{ unreachable; }"), profile="debug")
    assert "call void @llvm.trap()" in assert_ir
    assert "call void @llvm.trap()" in unreachable_ir
    assert "unreachable" in unreachable_ir


def test_llvm_codegen_debug_assert_removed_in_release() -> None:
    src = "fn main() Int{ debug_assert(true); return 0; }"
    ir_debug = to_llvm_ir(_analyzed(src), profile="debug")
    ir_release = to_llvm_ir(_analyzed(src), profile="release")
    assert "call void @llvm.trap()" in ir_debug
    assert "call void @llvm.trap()" not in ir_release


def test_llvm_codegen_likely_unlikely_attach_branch_weights() -> None:
    src = """
fn main() Int{
  x = 1;
  if likely(x > 0) {
    return 1;
  } else {
    return 0;
  }
}
"""
    ir_likely = to_llvm_ir(_analyzed(src), profile="release")
    assert "branch_weights" in ir_likely
    assert "i32 2000, i32 1" in ir_likely

    src_unlikely = """
fn main() Int{
  x = 1;
  if unlikely(x > 0) {
    return 1;
  } else {
    return 0;
  }
}
"""
    ir_unlikely = to_llvm_ir(_analyzed(src_unlikely), profile="release")
    assert "branch_weights" in ir_unlikely
    assert "i32 1, i32 2000" in ir_unlikely


def test_llvm_codegen_string_interpolation_uses_concat_not_format_runtime() -> None:
    src = 'fn main() Int{ print("a={1} b={true}"); return 0; }'
    ir = to_llvm_ir(_analyzed(src))
    assert "@astra_format_string" not in ir


def test_llvm_codegen_print_any_uses_display_runtime() -> None:
    src = 'fn main() Int{ a = "hello" as Any; print(a); return 0; }'
    ir = to_llvm_ir(_analyzed(src))
    assert "@astra_any_to_display" in ir


def test_llvm_codegen_returned_struct_keeps_heap_allocation() -> None:
    src = """
struct Pair { a Int, b Int }
fn make() Pair{
  return Pair(4, 6);
}
fn main() Int{
  p = make();
  return p.a + p.b;
}
"""
    ir = to_llvm_ir(_analyzed(src))
    assert "call i64 @astra_alloc(" in ir


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
