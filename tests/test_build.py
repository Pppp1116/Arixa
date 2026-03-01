import shutil
import subprocess
from pathlib import Path

import pytest

from astra.build import build


def test_build_py(tmp_path: Path):
    src = tmp_path / 'a.astra'
    src.write_text('fn main() -> Int { print("ok"); return 0; }')
    out = tmp_path / 'a.py'
    st = build(str(src), str(out), 'py')
    assert st in {'built','cached'}
    assert out.exists()


def test_build_emit_ir(tmp_path: Path):
    src = tmp_path / "a.astra"
    src.write_text("fn main() -> Int { let x = 1 + 2; return x; }")
    out = tmp_path / "a.py"
    ir = tmp_path / "a.ir.json"
    st = build(str(src), str(out), "py", emit_ir=str(ir))
    assert st in {"built", "cached"}
    assert ir.exists()
    assert '"name": "main"' in ir.read_text()


@pytest.mark.skipif(
    shutil.which("nasm") is None or shutil.which("ld") is None,
    reason="native target requires nasm and ld",
)
def test_build_native_executable(tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.exe"
    src.write_text("fn main() -> Int { return 7; }")
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    assert out.exists()
    assert out.stat().st_mode & 0o111
    rc = subprocess.call([str(out)])
    assert rc == 7


@pytest.mark.skipif(
    shutil.which("nasm") is None or shutil.which("ld") is None,
    reason="native target requires nasm and ld",
)
def test_build_native_runtime_builtins_link_and_run(tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.exe"
    src.write_text(
        """
fn main() -> Int {
  print("ok");
  let p = alloc(16);
  free(p);
  return 0;
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 0
    assert cp.stdout == "ok\n"


@pytest.mark.skipif(
    shutil.which("nasm") is None or shutil.which("ld") is None,
    reason="native target requires nasm and ld",
)
def test_build_native_runtime_panic_reports_message(tmp_path: Path):
    src = tmp_path / "panic.astra"
    out = tmp_path / "panic.exe"
    src.write_text(
        """
fn main() -> Int {
  panic("boom");
  return 0;
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 101
    assert "panic: boom" in cp.stderr


@pytest.mark.skipif(
    shutil.which("nasm") is None or shutil.which("ld") is None,
    reason="native target requires nasm and ld",
)
def test_build_native_supports_async_struct_and_defer_loop(tmp_path: Path):
    src = tmp_path / "combo.astra"
    out = tmp_path / "combo.exe"
    src.write_text(
        """
struct Pair { a Int, b Int }
async fn calc() -> Int {
  let mut p = Pair(2, 3);
  p.a += 4;
  return p.a + p.b;
}
fn main() -> Int {
  let mut i = 0;
  while i < 2 {
    defer print("bye");
    i += 1;
  }
  return calc();
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 9
    assert cp.stdout == "bye\nbye\n"


@pytest.mark.skipif(
    shutil.which("nasm") is None or shutil.which("ld") is None,
    reason="native target requires nasm and ld",
)
def test_build_native_supports_non_runtime_builtins(tmp_path: Path):
    src = tmp_path / "builtins.astra"
    out = tmp_path / "builtins.exe"
    src.write_text(
        """
fn main() -> Int {
  drop read_file("missing.txt");
  drop cwd();
  drop now_unix();
  drop monotonic_ms();
  drop len(1);
  return 0;
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 0


@pytest.mark.skipif(
    shutil.which("nasm") is None or shutil.which("ld") is None,
    reason="native target requires nasm and ld",
)
def test_build_native_supports_float_mod(tmp_path: Path):
    src = tmp_path / "fmod.astra"
    out = tmp_path / "fmod.exe"
    src.write_text(
        """
fn main() -> Int {
  let mut x = 7.5;
  x %= 2.0;
  if x > 1.4 && x < 1.6 {
    return 3;
  }
  return 0;
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 3
