from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_std_thread_and_atomic_runtime(tmp_path) -> None:
    src = '''
import "thread";
import "atomic";

fn fn worker() Int{() Int {
  return 41;
}

fn main() Int {
  tid = spawn0(worker);
  out: Int = join_task(tid) as Int;
  mut a = atomic_int_new(1);
  prev = atomic_fetch_add(&mut a, out);
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

fn main() Int {
  mut ch = channel_new();
  rc = channel_send(&mut ch, 7);
  if rc != 0 {
    return 1;
  }
  else {}
  v = channel_recv(&mut ch) ?? 0;
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


def test_spawn_returns_before_join(tmp_path) -> None:
    src = '''
import "thread";
import "time";

fn worker(ms Int) Int{
  _ = sleep_ms(ms);
  return 7;
}

fn main() Int {
  t0 = monotonic_ms();
  tid = spawn1(worker, 200);
  t1 = monotonic_ms();
  out: Int = join_task(tid) as Int;
  if out != 7 {
    return 2;
  }
  else {}
  if (t1 - t0) >= 180 {
    return 1;
  }
  else {}
  return 0;
}
'''
    results = compile_and_run_program(
        tmp_path,
        name="std_spawn_returns_before_join",
        src_text=src,
        backends=("py", "native"),
    )
    assert_same_stdout_and_exit(results, expected_stdout="", expected_returncode=0)
