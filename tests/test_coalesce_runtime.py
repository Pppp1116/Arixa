from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_coalesce_short_circuits_when_some(tmp_path) -> None:
    src = """
fn side() Int{
  print("rhs");
  return 7;
}

fn main() Int{
  x: Int? = 1;
  y = x ?? side();
  return y;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="coalesce_some",
        src_text=src,
        backends=("py", "native"),
    )
    backend_names = {r.backend for r in results}
    assert "py" in backend_names
    assert_same_stdout_and_exit(results, expected_stdout="", expected_returncode=1)


def test_coalesce_evaluates_rhs_when_none(tmp_path) -> None:
    src = """
fn side() Int{
  print("rhs");
  return 7;
}

fn main() Int{
  x: Int? = none;
  y = x ?? side();
  return y;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="coalesce_none",
        src_text=src,
        backends=("py", "native"),
    )
    backend_names = {r.backend for r in results}
    assert "py" in backend_names
    assert_same_stdout_and_exit(results, expected_stdout="rhs\n", expected_returncode=7)

