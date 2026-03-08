import subprocess
import sys
from pathlib import Path

from astra.asm_assert import assert_valid_llvm_ir
from astra.build import build


def test_complex_program_python_build_contains_precomputed_constants(tmp_path: Path):
    src = tmp_path / "complex.astra"
    out = tmp_path / "complex.py"
    src.write_text(
        """
fn norm(x Int) Int{ return x; }
fn norm(x Float) Float{ return x; }

fn fib(n Int) Int{
  if n <= 1 { return n; }
  return fib(n - 1) + fib(n - 2);
}

fn main() Int{
  comptime {
    k = fib(8);
    p = alloc(16);
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


def test_complex_program_llvm_ir_shape(tmp_path: Path):
    src = tmp_path / "x.astra"
    out = tmp_path / "x.ll"
    src.write_text(
        """
fn calc(a Int, b Int) Int{
  mut x = a;
  mut y = b;
  while y > 0 {
    x += 1;
    y -= 1;
  }
  return x;
}
fn main() Int{
  return calc(5, 7);
}
"""
    )
    build(str(src), str(out), "llvm")
    mod = out.read_text()
    assert_valid_llvm_ir(mod, workdir=tmp_path)
    assert "define i32 @main()" in mod
    assert "astra_run_py" not in mod


def test_llvm_if_program_is_valid(tmp_path: Path):
    src = tmp_path / "ifopt.astra"
    out = tmp_path / "ifopt.ll"
    src.write_text(
        """
fn cmp(a Int, b Int) Int{
  if a < b {
    return 1;
  }
  return 0;
}
fn main() Int{
  return cmp(3, 7);
}
"""
    )
    build(str(src), str(out), "llvm")
    mod = out.read_text()
    assert_valid_llvm_ir(mod, workdir=tmp_path)
    assert "define i32 @main()" in mod


def test_llvm_algebraic_program_is_valid(tmp_path: Path):
    src = tmp_path / "alg.astra"
    out = tmp_path / "alg.ll"
    src.write_text(
        """
fn main() Int{
  a = 7;
  b = (a * 1) + 0;
  return b;
}
"""
    )
    build(str(src), str(out), "llvm")
    mod = out.read_text()
    assert_valid_llvm_ir(mod, workdir=tmp_path)
    assert "define i32 @main()" in mod


def test_mutable_loop_variable_is_not_const_propagated(tmp_path: Path):
    src = tmp_path / "loop.astra"
    out = tmp_path / "loop.py"
    src.write_text(
        """
fn main() Int{
  mut i = 0;
  mut acc = 0;
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
