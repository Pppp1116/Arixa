from __future__ import annotations

import random

from golden_helpers import compile_and_run_program


def _gen_expr(rng: random.Random, depth: int) -> str:
    if depth <= 0:
        return str(rng.randint(-9, 9))
    op = rng.choice(["+", "-", "*", "/", "%"])
    left = _gen_expr(rng, depth - 1)
    if op in {"/", "%"}:
        right = str(rng.randint(1, 9))
    else:
        right = _gen_expr(rng, depth - 1)
    return f"({left} {op} {right})"


def test_random_arithmetic_is_consistent_between_py_and_native(tmp_path) -> None:
    rng = random.Random(1337)
    for i in range(20):
        expr = _gen_expr(rng, depth=3)
        src = f"""
fn main() Int{{
  x = {expr};
  print(x);
  return 0;
}}
"""
        results = compile_and_run_program(
            tmp_path,
            name=f"meta_expr_{i}",
            src_text=src,
            backends=("py", "native"),
        )
        assert len(results) >= 1
        py = next(r for r in results if r.backend == "py")
        for rr in results:
            assert rr.returncode == 0
            assert rr.stdout == py.stdout
