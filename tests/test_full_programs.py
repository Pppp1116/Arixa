import subprocess
import sys
from pathlib import Path

from astra.build import build


def _build_and_run(tmp_path: Path, name: str, src_text: str) -> subprocess.CompletedProcess[str]:
    src = tmp_path / f"{name}.astra"
    out = tmp_path / f"{name}.py"
    src.write_text(src_text)
    state = build(str(src), str(out), "py")
    assert state in {"built", "cached"}
    return subprocess.run([sys.executable, str(out)], capture_output=True, text=True, timeout=3)


def test_full_program_opcode_calculator(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "calculator",
        """
fn calc(op Int, a Int, b Int) -> Int {
  if op == 0 { return a + b; }
  if op == 1 { return a - b; }
  if op == 2 { return a * b; }
  if op == 3 { return a / b; }
  if op == 4 { return a % b; }
  return -1;
}

fn main() -> Int {
  let v1 = calc(0, 40, 2);
  let v2 = calc(2, 7, 6);
  let v3 = calc(4, 85, 43);
  if v2 != 42 { return 1; }
  if v3 != 42 { return 2; }
  return v1;
}
""",
    )
    assert cp.returncode == 42


def test_full_program_prime_counting(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "primes",
        """
fn is_prime(x Int) -> Bool {
  if x < 2 {
    return false;
  }
  let mut d = 2;
  while d * d <= x {
    if (x % d) == 0 {
      return false;
    }
    d += 1;
  }
  return true;
}

fn main() -> Int {
  let mut n = 2;
  let mut count = 0;
  while n <= 50 {
    if is_prime(n) {
      count += 1;
    }
    n += 1;
  }
  return count;
}
""",
    )
    assert cp.returncode == 15


def test_full_program_nested_loop_workload(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "nested_loops",
        """
fn main() -> Int {
  let mut i = 1;
  let mut total = 0;
  while i <= 5 {
    let mut j = 1;
    while j <= 5 {
      total += i * j;
      j += 1;
    }
    i += 1;
  }
  return total;
}
""",
    )
    assert cp.returncode == 225


def test_full_program_batch_gcd_accumulator(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "batch_gcd",
        """
fn gcd(a Int, b Int) -> Int {
  let mut x = a;
  let mut y = b;
  while y != 0 {
    let t = x % y;
    x = y;
    y = t;
  }
  return x;
}

fn main() -> Int {
  let mut i = 1;
  let mut acc = 0;
  while i <= 8 {
    acc += gcd(i * 12, i * 18);
    i += 1;
  }
  return acc;
}
""",
    )
    assert cp.returncode == 216


def test_full_program_comptime_recursive_fold(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "comptime_heavy",
        """
fn fib(n Int) -> Int {
  if n <= 1 { return n; }
  return fib(n - 1) + fib(n - 2);
}

fn main() -> Int {
  comptime {
    let pre = fib(10);
    let chk = pre + fib(7);
  }
  return chk - pre;
}
""",
    )
    assert cp.returncode == 13


def test_full_program_array_and_branch_flow(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "array_branch",
        """
fn main() -> Int {
  let mut i = 0;
  let mut sum = 0;
  while i < 3 {
    let v = [7, 9, 11][i];
    if (v % 2) == 1 {
      sum += v;
    }
    i += 1;
  }
  return sum;
}
""",
    )
    assert cp.returncode == 27


def test_full_program_struct_accumulator(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "struct_acc",
        """
struct Acc { total Int, count Int }

fn main() -> Int {
  let mut a = Acc(0, 0);
  let mut i = 1;
  while i <= 6 {
    a.total += i * i;
    a.count += 1;
    i += 1;
  }
  if a.count == 6 {
    return a.total;
  }
  return 1;
}
""",
    )
    assert cp.returncode == 91


def test_full_program_vector_workload(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "vector_workload",
        """
fn main() -> Int {
  let mut v: Vec<Int> = vec_new() as Vec<Int>;
  let mut i = 1;
  while i <= 6 {
    drop vec_push(v, i * i);
    i += 1;
  }
  drop vec_set(v, 0, 10);
  let got: Option<Int> = vec_get(v, 5);
  return vec_len(v) + (got ?? 0);
}
""",
    )
    assert cp.returncode == 42
