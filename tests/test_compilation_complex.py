import subprocess
import sys
from pathlib import Path

from astra.build import build


def test_complex_program_python_build_contains_precomputed_constants(tmp_path: Path):
    src = tmp_path / "complex.astra"
    out = tmp_path / "complex.py"
    src.write_text(
        """
impl fn norm(x Int) -> Int { return x; }
impl fn norm(x Float) -> Float { return x; }

fn fib(n Int) -> Int {
  if n <= 1 { return n; }
  return fib(n - 1) + fib(n - 2);
}

fn main() -> Int {
  comptime {
    let k = fib(8);
    let p = alloc(16);
    free(p);
  }
  if norm(k) == 21 {
    return 0;
  }
  return 1;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "alloc(16)" not in code
    assert "fib(8)" not in code
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 0


def test_complex_program_x86_assembly_shape(tmp_path: Path):
    src = tmp_path / "x.astra"
    out = tmp_path / "x.s"
    src.write_text(
        """
fn calc(a Int, b Int) -> Int {
  let mut x = a;
  let mut y = b;
  while y > 0 {
    x += 1;
    y -= 1;
  }
  return x;
}
fn main() -> Int {
  return calc(5, 7);
}
"""
    )
    build(str(src), str(out), "x86_64")
    asm = out.read_text()
    assert "call calc" in asm
    assert "while_begin" in asm
    # Comparison in loop condition should use direct branch lowering.
    assert "setg al" not in asm
    # Binary-op lowering avoids legacy register shuffle.
    assert "mov rbx, rax" not in asm


def test_x86_assembly_uses_direct_cmp_branch_for_if(tmp_path: Path):
    src = tmp_path / "ifopt.astra"
    out = tmp_path / "ifopt.s"
    src.write_text(
        """
fn cmp(a Int, b Int) -> Int {
  if a < b {
    return 1;
  }
  return 0;
}
fn main() -> Int {
  return cmp(3, 7);
}
"""
    )
    build(str(src), str(out), "x86_64")
    asm = out.read_text()
    assert "cmp rbx, rax" in asm
    assert "jge" in asm
    assert "setl al" not in asm


def test_x86_constant_if_is_pruned_before_codegen(tmp_path: Path):
    src = tmp_path / "ifconst.astra"
    out = tmp_path / "ifconst.s"
    src.write_text(
        """
fn main() -> Int {
  let mut x = 4;
  if 2 + 2 == 4 {
    x += 1;
  } else {
    x += 100;
  }
  return x;
}
"""
    )
    build(str(src), str(out), "x86_64")
    asm = out.read_text()
    assert "if_else" not in asm
    assert "if_end" not in asm


def test_x86_algebraic_simplification_removes_mul_and_add_zero(tmp_path: Path):
    src = tmp_path / "alg.astra"
    out = tmp_path / "alg.s"
    src.write_text(
        """
fn main() -> Int {
  let a = 7;
  let b = (a * 1) + 0;
  return b;
}
"""
    )
    build(str(src), str(out), "x86_64")
    asm = out.read_text()
    assert "imul" not in asm
    assert "add rax" not in asm


def test_mutable_loop_variable_is_not_const_propagated(tmp_path: Path):
    src = tmp_path / "loop.astra"
    out = tmp_path / "loop.py"
    src.write_text(
        """
fn main() -> Int {
  let mut i = 0;
  let mut acc = 0;
  while i < 4 {
    acc += 5 * 1;
    i += 1;
  }
  return acc;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 20
