from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_match_or_pattern_and_guard_runtime_parity(tmp_path) -> None:
    src = """
fn main() Int {
  x = 2;
  match x {
    1 | 2 if x == 2 => {
      print("hit");
      return 7;
    }
    _ => {
      return 0;
    }
  }
  return 9;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="match_or_guard_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="hit\n", expected_returncode=7)


def test_match_guard_fallthrough_runtime_parity(tmp_path) -> None:
    src = """
fn main() Int {
  x = 1;
  match x {
    1 if false => { return 10; }
    1 | 2 => { return 5; }
    _ => { return 0; }
  }
  return 9;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="match_guard_fallthrough_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="", expected_returncode=5)


def test_match_struct_destructuring_runtime_parity(tmp_path) -> None:
    src = """
struct Pair {
  a Int,
  b Int,
}

fn main() Int {
  p = Pair(9, 4);
  match p {
    Pair(x, y) => {
      print(x);
      print(y);
      return x + y;
    }
  }
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="match_struct_destructuring_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="9\n4\n", expected_returncode=13)


def test_match_range_pattern_runtime_parity(tmp_path) -> None:
    src = """
fn main() Int {
  x = 42;
  match x {
    0..=10 => {
      print("small");
      return 1;
    }
    11..50 => {
      print("mid");
      return 2;
    }
    _ => {
      print("large");
      return 3;
    }
  }
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="match_range_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="mid\n", expected_returncode=2)


def test_match_struct_brace_pattern_runtime_parity(tmp_path) -> None:
    src = """
struct Point {
  x Int,
  y Int,
}

fn main() Int {
  p = Point(2, 9);
  match p {
    Point { x: 1, y } => { return y; }
    Point { x, y: 9 } => {
      print(x);
      return x + 10;
    }
    _ => { return 0; }
  }
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="match_struct_brace_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="2\n", expected_returncode=12)


def test_match_slice_pattern_runtime_parity(tmp_path) -> None:
    src = """
fn main() Int {
  xs = [4, 7, 9];
  match xs {
    [a, b, ..] => {
      print(a);
      return a + b;
    }
    _ => { return 0; }
  }
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="match_slice_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="4\n", expected_returncode=11)


def test_match_tuple_pattern_runtime_parity(tmp_path) -> None:
    src = """
fn main() Int {
  xs = [2, 5];
  match xs {
    (x, y) => {
      print(y);
      return x + y;
    }
    _ => { return 0; }
  }
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="match_tuple_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="5\n", expected_returncode=7)
