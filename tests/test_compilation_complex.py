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
    assert "k = 21" in code
    assert "alloc(16)" not in code


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
