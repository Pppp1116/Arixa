from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_std_thread_and_atomic_runtime(tmp_path) -> None:
    src = '''
import "thread";
import "atomic";

fn worker() -> Int {
  return 41;
}

fn main() -> Int {
  let tid = spawn0(worker);
  let out: Int = join_task(tid) as Int;
  let mut a = atomic_int_new(1);
  let prev = atomic_fetch_add(&mut a, out);
  print(prev);
  return atomic_load(&a);
}
'''
    results = compile_and_run_program(
        tmp_path,
        name="std_thread_atomic_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="1\n", expected_returncode=42)


def test_std_channel_runtime(tmp_path) -> None:
    src = '''
import "channel";

fn main() -> Int {
  let mut ch = channel_new();
  let rc = channel_send(&mut ch, 7);
  if rc != 0 {
    return 1;
  }
  else {}
  let v = channel_recv(&mut ch) ?? 0;
  return v as Int;
}
'''
    results = compile_and_run_program(
        tmp_path,
        name="std_channel_runtime",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="", expected_returncode=7)
