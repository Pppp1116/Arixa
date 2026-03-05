from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_try_operator_propagates_none_and_short_circuits(tmp_path) -> None:
    src = """
fn maybe(v Int) -> Option<Int> {
  if v > 0 {
    return v;
  }
  else {}
  return none;
}

fn helper(v Int) -> Option<Int> {
  let x = maybe(v)?;
  print("after");
  return x + 1;
}

fn main() -> Int {
  let a = helper(0) ?? 7;
  let b = helper(1) ?? 0;
  return a + b;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="try_propagate_none",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="after\n", expected_returncode=9)


def test_try_operator_runs_defers_on_early_return(tmp_path) -> None:
    src = """
fn helper(v: Option<Int>) -> Option<Int> {
  defer print("cleanup");
  let x = v?;
  return x;
}

fn main() -> Int {
  let mut input: Option<Int> = none;
  let out = helper(input) ?? 5;
  return out;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="try_defer_cleanup",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="cleanup\n", expected_returncode=5)


def test_try_operator_propagates_result_err_and_short_circuits(tmp_path) -> None:
    src = """
enum Result<T, E> {
  Ok(T),
  Err(E),
}

fn parse(v Int) -> Result<Int, Int> {
  if v > 0 {
    return Result.Ok(v);
  }
  else {}
  return Result.Err(404);
}

fn add1(v Int) -> Result<Int, Int> {
  let x = parse(v)?;
  print("after-ok");
  return Result.Ok(x + 1);
}

fn main() -> Int {
  print(to_json(add1(2)));
  print(to_json(add1(0)));
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="try_result_propagation",
        src_text=src,
        backends=("py",),
    )
    assert_same_stdout_and_exit(
        results,
        expected_stdout=(
            "after-ok\n"
            '{"__enum__": "Result", "tag": "Ok", "values": [3]}\n'
            '{"__enum__": "Result", "tag": "Err", "values": [404]}\n'
        ),
        expected_returncode=0,
    )


def test_try_operator_result_propagation_matches_py_and_native(tmp_path) -> None:
    src = """
enum Result<T, E> {
  Ok(T),
  Err(E),
}

fn parse(v Int) -> Result<Int, Int> {
  if v > 0 {
    return Result.Ok(v);
  }
  else {}
  return Result.Err(1);
}

fn helper(v Int) -> Result<Int, Int> {
  let x = parse(v)?;
  print("after");
  return Result.Ok(x + 1);
}

fn main() -> Int {
  let _ = helper(0);
  let _ = helper(1);
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="try_result_parity",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="after\n", expected_returncode=0)
