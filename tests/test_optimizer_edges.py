import subprocess
import sys
from pathlib import Path

from astra.build import build


def test_dead_pure_lets_are_removed(tmp_path: Path):
    src = tmp_path / "dead_lets.astra"
    out = tmp_path / "dead_lets.py"
    src.write_text(
        """
fn main() -> Int {
  let a = 1 + 2;
  let b = 9 * 3;
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "a =" not in code
    assert "b =" not in code


def test_dead_let_with_side_effect_is_preserved_as_expr(tmp_path: Path):
    src = tmp_path / "dead_side.astra"
    out = tmp_path / "dead_side.py"
    src.write_text(
        """
fn main() -> Int {
  let x = print(7);
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "x =" not in code
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=2)
    assert cp.returncode == 0
    assert "7" in cp.stdout


def test_dead_trapping_expr_statement_is_not_removed(tmp_path: Path):
    src = tmp_path / "trap_expr.astra"
    out = tmp_path / "trap_expr.py"
    src.write_text(
        """
fn main() -> Int {
  drop 1 / 0;
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=2)
    assert cp.returncode != 0
    assert "ZeroDivisionError" in cp.stderr


def test_dead_trapping_let_initializer_is_not_removed(tmp_path: Path):
    src = tmp_path / "trap_let.astra"
    out = tmp_path / "trap_let.py"
    src.write_text(
        """
fn main() -> Int {
  let x = 1 / 0;
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=2)
    assert cp.returncode != 0
    assert "ZeroDivisionError" in cp.stderr


def test_mul_zero_does_not_drop_trapping_subexpression(tmp_path: Path):
    src = tmp_path / "mul_zero_trap.astra"
    out = tmp_path / "mul_zero_trap.py"
    src.write_text(
        """
fn main() -> Int {
  return (1 / 0) * 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=2)
    assert cp.returncode != 0
    assert "ZeroDivisionError" in cp.stderr


def test_short_circuit_false_and_still_short_circuits(tmp_path: Path):
    src = tmp_path / "short_and.astra"
    out = tmp_path / "short_and.py"
    src.write_text(
        """
fn main() -> Int {
  let x = false && (1 / 0 == 0);
  if x { return 1; }
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 0


def test_optimizer_fixed_point_propagates_constant_chain(tmp_path: Path):
    src = tmp_path / "chain.astra"
    out = tmp_path / "chain.py"
    src.write_text(
        """
fn main() -> Int {
  let a = 1 + 2;
  let b = a + 3;
  let c = b * 2;
  return c;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "return 12" in code
    assert "a =" not in code
    assert "b =" not in code
    assert "c =" not in code


def test_local_cse_reuses_identical_pure_expression(tmp_path: Path):
    src = tmp_path / "cse.astra"
    out = tmp_path / "cse.py"
    src.write_text(
        """
fn main() -> Int {
  let mut x = 7;
  let y = x * x;
  let z = x * x;
  return z - y;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "z = y" in code
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 0


def test_strength_reduction_mul_pow2_to_shift(tmp_path: Path):
    src = tmp_path / "strength.astra"
    out = tmp_path / "strength.py"
    src.write_text(
        """
fn main() -> Int {
  let mut x = 3;
  let y = x * 8;
  return y;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "<<" in code
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 24
