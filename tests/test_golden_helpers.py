from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_compile_and_run_py_and_native_backends(tmp_path) -> None:
    # Simple program that exercises stdout and exit codes consistently.
    src = """
fn main() Int{
  print("ok");
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="hello_golden",
        src_text=src,
        backends=("py", "native"),
    )
    # At minimum we should always exercise the Python backend; native is
    # included when clang is available (otherwise the helper skips the test).
    backend_names = {r.backend for r in results}
    assert "py" in backend_names
    assert_same_stdout_and_exit(results, expected_stdout="ok\n", expected_returncode=0)


def test_compile_and_run_llvm_ir_build(tmp_path) -> None:
    # LLVM path: treat stdout as IR text so tests can assert CODEGEN details.
    src = """
fn main() Int{
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="hello_ir",
        src_text=src,
        backends=("llvm",),
    )
    assert len(results) == 1
    llvm_result = results[0]
    assert llvm_result.backend == "llvm"
    # Sanity check that the IR looks like a main function definition.
    assert "define i32 @main()" in llvm_result.stdout


def test_multiline_string_behaves_consistently_across_backends(tmp_path) -> None:
    src = """
fn main() Int{
  s = \"\"\"a
b\"\"\";
  print(s);
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="multiline_str",
        src_text=src,
        backends=("py", "native"),
    )
    backend_names = {r.backend for r in results}
    assert "py" in backend_names
    # The printed value includes the multiline contents plus print's newline.
    assert_same_stdout_and_exit(results, expected_stdout="a\nb\n", expected_returncode=0)


def test_range_for_and_match_wildcard_consistent_across_backends(tmp_path) -> None:
    src = """
fn main() Int{
  mut total = 0;
  for i in 1..=5 {
    total += i;
  }
  match total == 15 {
    true => { print("ok"); }
    _ => { print("bad"); }
  }
  return total;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="range_match_wildcard",
        src_text=src,
        backends=("py", "native"),
    )
    backend_names = {r.backend for r in results}
    assert "py" in backend_names
    assert_same_stdout_and_exit(results, expected_stdout="ok\n", expected_returncode=15)
