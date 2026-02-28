from pathlib import Path

from astra.build import build
from astra.comptime import run_comptime
from astra.parser import parse


def test_parse_comptime_block():
    prog = parse("fn main() -> Int { comptime { let x = 1; } return 0; }")
    fn = prog.items[0]
    assert fn.body and fn.body[0].__class__.__name__ == "ComptimeStmt"


def test_comptime_evaluates_function_calls_and_loops(tmp_path: Path):
    src = tmp_path / "c.astra"
    out = tmp_path / "c.py"
    src.write_text(
        """
fn gen(n Int) -> Int {
  let mut i = 0;
  let mut acc = 0;
  while i < n {
    acc += i;
    i += 1;
  }
  return acc;
}

fn main() -> Int {
  comptime {
    let total = gen(10);
  }
  return total;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "total = 45" in code


def test_comptime_alloc_free(tmp_path: Path):
    src = """
fn main() -> Int {
  comptime {
    let p = alloc(32);
    free(p);
    let x = 7;
  }
  return x;
}
"""
    prog = parse(src)
    pool = run_comptime(prog)
    assert pool.get("main:x") == 7


def test_comptime_no_io_allowed(tmp_path: Path):
    src = tmp_path / "bad.astra"
    out = tmp_path / "bad.py"
    src.write_text(
        """
fn main() -> Int {
  comptime {
    print("no");
  }
  return 0;
}
"""
    )
    try:
        build(str(src), str(out), "py")
        assert False
    except Exception as e:
        assert "non-pure function print" in str(e)
