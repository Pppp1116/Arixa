import subprocess
import sys
from pathlib import Path

from astra.build import build
from astra.comptime import run_comptime
from astra.parser import parse


def test_parse_comptime_block():
    prog = parse("fn main() Int{ comptime { x = 1; } return 0; }")
    fn = prog.items[0]
    assert fn.body and fn.body[0].__class__.__name__ == "ComptimeStmt"


def test_comptime_evaluates_function_calls_and_loops(tmp_path: Path):
    src = tmp_path / "c.arixa"
    out = tmp_path / "c.py"
    src.write_text(
        """
fn gen(n Int) Int{
  mut i = 0;
  mut acc = 0;
  while i < n {
    acc += i;
    i += 1;
  }
  return acc;
}

fn main() Int{
  comptime {
    total = gen(10);
  }
  return total;
}
"""
    )
    build(str(src), str(out), "py")
    code = out.read_text()
    assert "gen(10)" not in code
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 45


def test_comptime_alloc_free(tmp_path: Path):
    src = """
fn main() Int{
  comptime {
    p = alloc(32);
    free(p);
    x = 7;
  }
  return x;
}
"""
    prog = parse(src)
    pool = run_comptime(prog)
    assert pool.get("main:x") == 7


def test_comptime_no_io_allowed(tmp_path: Path):
    src = tmp_path / "bad.arixa"
    out = tmp_path / "bad.py"
    src.write_text(
        """
fn main() Int{
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


def test_comptime_match_is_evaluated(tmp_path: Path):
    src = tmp_path / "match.arixa"
    out = tmp_path / "match.py"
    src.write_text(
        """
fn main() Int{
  comptime {
    x = 2;
    mut out = 0;
    match x {
      1 => { out = 11; }
      2 => { out = 22; }
    }
  }
  return out;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 22


def test_comptime_supports_indirect_function_calls(tmp_path: Path):
    src = tmp_path / "indirect.arixa"
    out = tmp_path / "indirect.py"
    src.write_text(
        """
fn add(a Int, b Int) Int{ return a + b; }
fn main() Int{
  comptime {
    f = add;
    z = f(5, 7);
  }
  return z;
}
"""
    )
    build(str(src), str(out), "py")
    text = out.read_text()
    assert "f(5, 7)" not in text
    cp = subprocess.run([sys.executable, str(out)], timeout=2)
    assert cp.returncode == 12


def test_comptime_skips_non_escaping_runtime_materialization(tmp_path: Path):
    src = tmp_path / "skip_tmp.arixa"
    out = tmp_path / "skip_tmp.py"
    src.write_text(
        """
fn main() Int{
  comptime {
    internal = 7;
  }
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    text = out.read_text()
    assert "internal = 7" not in text


def test_comptime_try_operator_reports_current_syntax(tmp_path: Path):
    src = tmp_path / "try_not_supported.arixa"
    out = tmp_path / "try_not_supported.py"
    src.write_text(
        """
fn maybe() Int?{
  return 1;
}
fn main() Int{
  comptime {
    x = maybe()!;
  }
  return x ?? 0;
}
"""
    )
    try:
        build(str(src), str(out), "py")
        assert False
    except Exception as e:
        assert "`!` is not supported in comptime expressions" in str(e)


def test_comptime_bans_time_builtins_for_determinism(tmp_path: Path):
    src = tmp_path / "time_banned.arixa"
    out = tmp_path / "time_banned.py"
    src.write_text(
        """
fn main() Int{
  comptime {
    t = now_unix();
  }
  return 0;
}
"""
    )
    try:
        build(str(src), str(out), "py")
        assert False
    except Exception as e:
        assert "non-pure function now_unix" in str(e)
