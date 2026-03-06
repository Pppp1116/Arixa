from __future__ import annotations

import random
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from astra.asm_assert import assert_valid_llvm_ir
from astra.build import build


def _run_py(tmp_path: Path, name: str, src: str) -> int:
    src_file = tmp_path / f"{name}.astra"
    out_file = tmp_path / f"{name}.py"
    src_file.write_text(src)
    st = build(str(src_file), str(out_file), "py")
    assert st in {"built", "cached"}
    cp = subprocess.run([sys.executable, str(out_file)], timeout=5)
    return cp.returncode


def _run_llvm_validate(tmp_path: Path, name: str, src: str) -> str:
    src_file = tmp_path / f"{name}.astra"
    out_file = tmp_path / f"{name}.ll"
    src_file.write_text(src)
    st = build(str(src_file), str(out_file), "llvm")
    assert st in {"built", "cached"}
    ir = out_file.read_text()
    assert_valid_llvm_ir(ir, workdir=tmp_path)
    return ir


def _run_native(tmp_path: Path, name: str, src: str) -> int:
    src_file = tmp_path / f"{name}.astra"
    out_file = tmp_path / f"{name}.exe"
    src_file.write_text(src)
    st = build(str(src_file), str(out_file), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out_file)], timeout=5)
    return cp.returncode


CASES: list[tuple[str, str, int]] = [
    (
        "comptime_match_indirect_call",
        """
fn add(a Int, b Int) Int{ return a + b; }
fn main() Int{
  comptime {
    f = add;
    x = f(7, 9);
    mut y = 0;
    match x {
      15 => { y = 1; }
      16 => { y = 3; }
    }
  }
  return x + y;
}
""",
        19,
    ),
    (
        "packed_wide_fields",
        """
@packed struct Wide {
  pad: u7,
  big: u128,
  tail: u1,
}
fn main() Int{
  mut w = Wide(2u7, 3u128, 1u1);
  w.big += 5u128;
  w.big <<= 1u128;
  return (w.pad as Int) + (w.big as Int) + (w.tail as Int);
}
""",
        19,
    ),
    (
        "for_forms_and_defer",
        """
fn main() Int{
  mut acc = 0;
  for i in 0..3 {
    defer print("tick");
    acc += i;
  }
  for j in 4..7 {
    acc += j;
  }
  return acc;
}
""",
        18,
    ),
    (
        "vec_option_coalesce",
        """
fn main() Int{
  mut v: Vec<Int> = vec_new() as Vec<Int>;
  drop vec_push(v, 10);
  drop vec_push(v, 20);
  a: Option<Int> = vec_get(v, 0);
  b: Option<Int> = vec_get(v, 99);
  return (a ?? 0) + (b ?? 3) + vec_len(v);
}
""",
        15,
    ),
    (
        "bit_intrinsics_widths",
        """
fn main() Int{
  x: u4 = 3u4;
  c = countOnes(x);
  l = leadingZeros(x);
  t = trailingZeros(x);
  return c + l + t;
}
""",
        4,
    ),
    (
        "fn_ptr_and_casts",
        """
fn mul(a Int, b Int) Int{ return a * b; }
fn main() Int{
  f = mul;
  x = f(5, 7);
  y: u8 = 9 as u8;
  z: Int = y as Int;
  return x + z;
}
""",
        44,
    ),
    (
        "layout_queries",
        """
struct P { a: Int, b: u8 }
fn main() Int{
  p = P(1, 2 as u8);
  return sizeof(P) + alignof(P) + size_of(p.a) + align_of(p.b);
}
""",
        33,
    ),
    (
        "bool_match_control",
        """
fn main() Int{
  b = true;
  match b {
    true => { return 7; }
    false => { return 9; }
  }
  return 0;
}
""",
        7,
    ),
]


@pytest.mark.parametrize("name,src,expected_rc", CASES, ids=[c[0] for c in CASES])
def test_heavy_feature_matrix_python_backend(tmp_path: Path, name: str, src: str, expected_rc: int):
    assert _run_py(tmp_path, name, src) == expected_rc


@pytest.mark.parametrize("name,src,_expected_rc", CASES, ids=[c[0] for c in CASES])
def test_heavy_feature_matrix_llvm_valid_ir(tmp_path: Path, name: str, src: str, _expected_rc: int):
    ir = _run_llvm_validate(tmp_path, name, src)
    assert "define i32 @main()" in ir


@pytest.mark.skipif(shutil.which("clang") is None, reason="native target requires clang")
@pytest.mark.parametrize("name,src,expected_rc", CASES, ids=[c[0] for c in CASES])
def test_heavy_feature_matrix_native_backend(tmp_path: Path, name: str, src: str, expected_rc: int):
    assert _run_native(tmp_path, name, src) == expected_rc


def _gen_expr(rng: random.Random, depth: int) -> tuple[str, int]:
    if depth <= 0:
        v = rng.randint(0, 63)
        return str(v), v
    ops = ["+", "-", "*", "&", "|", "^", "<<", ">>"]
    op = rng.choice(ops)
    left_s, left_v = _gen_expr(rng, depth - 1)
    right_s, right_v = _gen_expr(rng, depth - 1)
    if op in {"<<", ">>"}:
        right_v = right_v % 5
        right_s = str(right_v)
    if op == "+":
        out_v = left_v + right_v
    elif op == "-":
        out_v = left_v - right_v
    elif op == "*":
        out_v = left_v * right_v
    elif op == "&":
        out_v = left_v & right_v
    elif op == "|":
        out_v = left_v | right_v
    elif op == "^":
        out_v = left_v ^ right_v
    elif op == "<<":
        out_v = left_v << right_v
    else:
        out_v = left_v >> right_v
    return f"({left_s} {op} {right_s})", out_v


def test_heavy_randomized_arithmetic_matrix_py_backend(tmp_path: Path):
    rng = random.Random(1337)
    for i in range(80):
        expr, expected = _gen_expr(rng, depth=3)
        src = f"fn main() Int{{ return {expr}; }}\n"
        rc = _run_py(tmp_path, f"rand_py_{i}", src)
        assert rc == (expected % 256)


def test_heavy_randomized_arithmetic_matrix_llvm_builds(tmp_path: Path):
    rng = random.Random(7331)
    for i in range(60):
        expr, _expected = _gen_expr(rng, depth=3)
        src = f"fn main() Int{{ return {expr}; }}\n"
        ir = _run_llvm_validate(tmp_path, f"rand_llvm_{i}", src)
        assert "define i32 @main()" in ir
