import sys

import pytest

from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


@pytest.mark.skipif(sys.platform.startswith("win"), reason="process shell parity test uses POSIX `true`/`false` commands")
def test_std_process_runtime_parity(tmp_path) -> None:
    src = """
import "process";

fn main() Int{
  miss = env("ASTRA_PARITY_MISSING_KEY_7B9D1");
  if len(miss) != 0 {
    return 11;
  }
  else {}
  dir = cwd();
  if len(dir) == 0 {
    return 12;
  }
  else {}
  ok = run("true");
  bad = run("false");
  print(ok);
  print(bad);
  if ok == 0 && bad == 1 {
    return 0;
  }
  else {}
  return 13;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="std_process_runtime_parity",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="0\n1\n", expected_returncode=0)
