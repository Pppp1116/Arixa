from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_trait_where_bound_runtime_parity(tmp_path) -> None:
    src = """
trait Show {
  fn show(x Self) String;
}
fn show(x Int) String { return "ok"; }

fn wrap(x T) T where T: Show{
  return x;
}

fn main() Int {
  return wrap(7);
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="trait_where_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="", expected_returncode=7)
