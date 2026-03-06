from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_match_or_pattern_and_guard_runtime_parity(tmp_path) -> None:
    src = """
fn main() Int{
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
fn main() Int{
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
