from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_try_operator_propagates_none_and_short_circuits(tmp_path) -> None:
    src = """
fn maybe(v Int) Int?{
  if v > 0 {
    return v;
  }
  else {}
  return none;
}

fn helper(v Int) Int?{
  x = maybe(v)!;
  print("after");
  return x + 1;
}

fn main() Int{
  a = helper(0) ?? 7;
  b = helper(1) ?? 0;
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
fn helper(v Int?) Int?{
  defer print("cleanup");
  x = v!;
  return x;
}

fn main() Int{
  mut input: Int? = none;
  out = helper(input) ?? 5;
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


def test_try_operator_propagates_union_err_and_short_circuits(tmp_path) -> None:
    src = """
fn parse(v Int) Int | none{
  if v > 0 {
    return v;
  }
  else {}
  return none;
}

fn add1(v Int) Int | none{
  x = parse(v)!;
  print("after-ok");
  return x + 1;
}

fn main() Int{
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
            "3\n"
            "null\n"
        ),
        expected_returncode=0,
    )


def test_try_operator_union_propagation_matches_py_and_native(tmp_path) -> None:
    src = """
fn parse(v Int) Int | none{
  if v > 0 {
    return v;
  }
  else {}
  return none;
}

fn helper(v Int) Int | none{
  x = parse(v)!;
  print("after");
  return x + 1;
}

fn main() Int{
  _ = helper(0);
  _ = helper(1);
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
