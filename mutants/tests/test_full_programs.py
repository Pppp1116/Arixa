import subprocess
import sys
from pathlib import Path

from astra.build import build


def _build_and_run(tmp_path: Path, name: str, src_text: str) -> subprocess.CompletedProcess[str]:
    src = tmp_path / f"{name}.arixa"
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
fn calc(op Int, a Int, b Int) Int{
  if op == 0 { return a + b; }
  if op == 1 { return a - b; }
  if op == 2 { return a * b; }
  if op == 3 { return a / b; }
  if op == 4 { return a % b; }
  return -1;
}

fn main() Int{
  v1 = calc(0, 40, 2);
  v2 = calc(2, 7, 6);
  v3 = calc(4, 85, 43);
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
fn is_prime(x Int) Bool{
  if x < 2 {
    return false;
  }
  mut d = 2;
  while d * d <= x {
    if (x % d) == 0 {
      return false;
    }
    d += 1;
  }
  return true;
}

fn main() Int{
  mut n = 2;
  mut count = 0;
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
fn main() Int{
  mut i = 1;
  mut total = 0;
  while i <= 5 {
    mut j = 1;
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
fn gcd(a Int, b Int) Int{
  mut x = a;
  mut y = b;
  while y != 0 {
    t = x % y;
    x = y;
    y = t;
  }
  return x;
}

fn main() Int{
  mut i = 1;
  mut acc = 0;
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
fn fib(n Int) Int{
  if n <= 1 { return n; }
  return fib(n - 1) + fib(n - 2);
}

fn main() Int{
  comptime {
    pre = fib(10);
    chk = pre + fib(7);
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
fn main() Int{
  mut i = 0;
  mut sum = 0;
  while i < 3 {
    v = [7, 9, 11][i];
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

fn main() Int{
  mut a = Acc(0, 0);
  mut i = 1;
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
fn main() Int{
  mut v: Vec<Int> = vec_new() as Vec<Int>;
  mut i = 1;
  while i <= 6 {
    vec_push(v, i * i);
    i += 1;
  }
  vec_set(v, 0, 10);
  got: Int? = vec_get(v, 5);
  return vec_len(v) + (got ?? 0);
}
""",
    )
    assert cp.returncode == 42


def test_full_program_literals_alias_intrinsics_and_json_shapes(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "literals_json",
        """
fn main() Int{
  a = 0x2A;
  x: u8 = 0b1010_0101u8;
  mut m = map_new();
  map_set(m, "k", 1);
  xs = list_new();
  list_push(xs, 4);
  list_push(xs, 5);
  map_set(m, "xs", xs);
  js = to_json(m);
  rt = from_json(js);
  got = map_get(rt, "k") as Int;
  ys = map_get(rt, "xs");
  y1 = list_get(ys, 1) as Int;
  s = "a" + "b";
  r: u8 = rotr(rotl(x, 1u8), 1u8);
  return a + popcnt(x) + (r as Int) + got + y1 + len(s);
}
""",
    )
    assert cp.returncode == 219


def test_full_program_for_in_ranges(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "for_in_ranges",
        """
fn main() Int{
  mut a = 0;
  for i in 0..5 { a += i; }
  mut b = 0;
  for i in 0..=5 { b += i; }
  return a + b;
}
""",
    )
    assert cp.returncode == 25


def test_full_program_for_in_vec_and_bytes(tmp_path: Path):
    cp = _build_and_run(
        tmp_path,
        "for_in_vec_bytes",
        """
fn main() Int{
  mut v: Vec<Int> = vec_new() as Vec<Int>;
  vec_push(v, 4);
  vec_push(v, 5);
  vec_push(v, 6);
  mut sum_v = 0;
  for x in v { sum_v += x; }

  bs: Bytes = vec_from([1u8, 2u8, 3u8, 4u8]);
  mut sum_b = 0;
  for b in bs { sum_b += b as Int; }
  return sum_v + sum_b;
}
""",
    )
    assert cp.returncode == 25
