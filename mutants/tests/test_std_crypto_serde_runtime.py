from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_std_crypto_runtime_parity(tmp_path) -> None:
    src = """
import "crypto";

fn main() Int{
  a = sha256("abc");
  b = hmac_sha256("k", "v");
  c = digest_pair("left", "right");
  print(len(a));
  print(len(b));
  if a == c {
    return 9;
  }
  else {}
  return len(c);
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="std_crypto_runtime_parity",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="64\n64\n", expected_returncode=64)


def test_std_serde_runtime_parity(tmp_path) -> None:
    src = """
import "serde";

fn main() Int{
  m = map_new();
  _ = map_set(m, "alpha", 11);
  _ = map_set(m, "beta", 5);
  txt = to_json(m);
  rt = from_json(txt);
  a = map_get(rt, "alpha") as Int;
  b = map_get(rt, "beta") as Int;
  return (a * 10) + b;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="std_serde_runtime_parity",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="", expected_returncode=115)
