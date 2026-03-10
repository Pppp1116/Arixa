import re
import subprocess
import sys
from pathlib import Path

from astra.ast import Call, Literal, Name
from astra.build import build
from astra.optimizer.optimizer import _fold_pure_call_const


def test_dead_pure_lets_are_removed(tmp_path: Path):
    src = tmp_path / "dead_lets.arixa"
    out = tmp_path / "dead_lets.py"
    src.write_text(
        """
fn main() Int {
  a = 1 + 2;
  b = 9 * 3;
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert re.search(r"(?m)^    a =", code) is None
    assert re.search(r"(?m)^    b =", code) is None


def test_dead_let_with_side_effect_is_preserved_as_expr(tmp_path: Path):
    src = tmp_path / "dead_side.arixa"
    out = tmp_path / "dead_side.py"
    src.write_text(
        """
fn main() Int {
  x = print(7);
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert re.search(r"(?m)^    x =", code) is None
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=2)
    assert cp.returncode == 0
    assert "7" in cp.stdout


def test_dead_trapping_expr_statement_is_not_removed(tmp_path: Path):
    src = tmp_path / "trap_expr.arixa"
    out = tmp_path / "trap_expr.py"
    src.write_text(
        """
fn main() Int {
  1 / 0;
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=2)
    assert cp.returncode != 0
    assert "ZeroDivisionError" in cp.stderr


def test_dead_trapping_let_initializer_is_not_removed(tmp_path: Path):
    src = tmp_path / "trap_let.arixa"
    out = tmp_path / "trap_let.py"
    src.write_text(
        """
fn main() Int {
  x = 1 / 0;
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=2)
    assert cp.returncode != 0
    assert "ZeroDivisionError" in cp.stderr


def test_mul_zero_does_not_drop_trapping_subexpression(tmp_path: Path):
    src = tmp_path / "mul_zero_trap.arixa"
    out = tmp_path / "mul_zero_trap.py"
    src.write_text(
        """
fn main() Int {
  return (1 / 0) * 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=2)
    assert cp.returncode != 0
    assert "ZeroDivisionError" in cp.stderr


def test_short_circuit_false_and_still_short_circuits(tmp_path: Path):
    src = tmp_path / "short_and.arixa"
    out = tmp_path / "short_and.py"
    src.write_text(
        """
fn main() Int {
  x = false && (1 / 0 == 0);
  if x { return 1; }
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 0


def test_optimizer_fixed_point_propagates_constant_chain(tmp_path: Path):
    src = tmp_path / "chain.arixa"
    out = tmp_path / "chain.py"
    src.write_text(
        """
fn main() Int {
  a = 1 + 2;
  b = a + 3;
  c = b * 2;
  return c;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "return 12" in code
    user_main = code.split("def main(", 1)[1]
    assert "a =" not in user_main
    assert "b =" not in user_main
    assert "c =" not in user_main


def test_local_cse_reuses_identical_pure_expression(tmp_path: Path):
    src = tmp_path / "cse.astra"
    out = tmp_path / "cse.py"
    src.write_text(
        """
fn main() Int {
  mut x = 7;
  y = x * x;
  z = x * x;
  return z - y;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "z = y" in code
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 0


def test_strength_reduction_mul_pow2_respects_overflow_mode(tmp_path: Path):
    src = tmp_path / "strength.astra"
    out_trap = tmp_path / "strength_trap.py"
    out_wrap = tmp_path / "strength_wrap.py"
    src.write_text(
        """
fn main() Int {
  mut x = 3;
  y = x * 8;
  return y;
}
"""
    )
    build(str(src), str(out_trap), "py")
    trap_code = out_trap.read_text()
    trap_main = trap_code.split("def main(", 1)[1].split("if __name__", 1)[0]
    assert "<<" not in trap_main
    assert "y = (x * 8)" in trap_main
    cp = subprocess.run([sys.executable, str(out_trap)], timeout=2)
    assert cp.returncode == 24

    build(str(src), str(out_wrap), "py", overflow="wrap")
    wrap_code = out_wrap.read_text()
    wrap_main = wrap_code.split("def main(", 1)[1].split("if __name__", 1)[0]
    assert "<<" in wrap_main
    cp = subprocess.run([sys.executable, str(out_wrap)], timeout=2)
    assert cp.returncode == 24


def test_match_range_with_constant_subject_folds_to_single_arm(tmp_path: Path):
    src = tmp_path / "match_range_fold.arixa"
    out = tmp_path / "match_range_fold.py"
    src.write_text(
        """
fn main() Int {
  x = 5;
  match x {
    1..=10 => { return 7; }
    _ => { return 0; }
  }
  return 9;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "__match_value" not in code
    assert "return 7" in code
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 7


def test_builtin_len_of_array_literal_folds_to_constant(tmp_path: Path):
    src = tmp_path / "len_fold.arixa"
    out = tmp_path / "len_fold.py"
    src.write_text(
        """
fn main() Int {
  return len([3, 4, 5, 6]);
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "return 4" in code
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 4


def test_stdlib_helper_fold_is_guarded_by_stdlib_source_marker():
    call = Call(
        fn=Name("abs_int", 0, 0, 0),
        args=[Literal(-7, 0, 0, 0)],
        pos=0,
        line=0,
        col=0,
        resolved_name="abs_int",
    )
    setattr(call, "resolved_source_filename", "/tmp/stdlib/math.arixa")
    out = _fold_pure_call_const(call)
    assert isinstance(out, Literal)
    assert out.value == 7
