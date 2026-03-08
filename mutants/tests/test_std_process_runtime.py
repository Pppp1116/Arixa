import sys

from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program

def test_std_process_runtime_parity(tmp_path) -> None:
    ok_cmd = "cmd /c exit 0" if sys.platform.startswith("win") else "true"
    bad_cmd = "cmd /c exit 1" if sys.platform.startswith("win") else "false"
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
  ok = run("__OK_CMD__");
  bad = run("__BAD_CMD__");
  print(ok);
  print(bad);
  if ok == 0 && bad == 1 {
    return 0;
  }
  else {}
  return 13;
}
"""
    src = src.replace("__OK_CMD__", ok_cmd).replace("__BAD_CMD__", bad_cmd)
    results = compile_and_run_program(
        tmp_path,
        name="std_process_runtime_parity",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="0\n1\n", expected_returncode=0)
