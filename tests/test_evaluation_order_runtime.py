from golden_helpers import assert_same_stdout_and_exit, compile_and_run_program


def test_binary_ops_and_call_args_are_left_to_right(tmp_path) -> None:
    src = """
struct Box { x Int }

fn log(x Int, tag Int) Int{
  print(tag);
  return x;
}

fn add(a Int, b Int) Int{
  return a + b;
}

fn make() Box{
  print(5);
  return Box(1);
}

fn get(b Box) Int{
  print(6);
  return b.x;
}

fn main() Int {
  _ = log(1, 1) + log(2, 2);
  _ = add(log(3, 3), log(4, 4));
  _ = get(make());
  return 0;
}
"""
    results = compile_and_run_program(
        tmp_path,
        name="eval_order",
        src_text=src,
        backends=("py", "native"),
    )
    backend_names = {r.backend for r in results}
    assert "py" in backend_names
    # Expected print sequence (one integer per line):
    #  - 1 then 2 from binary `log` calls
    #  - 3 then 4 from `add(log(...), log(...))` arguments
    #  - 5 then 6 from `get(make())` (base expression before call body)
    assert_same_stdout_and_exit(results, expected_stdout="1\n2\n3\n4\n5\n6\n", expected_returncode=0)

