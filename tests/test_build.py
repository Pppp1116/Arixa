import shutil
import subprocess
from pathlib import Path

import pytest

import astra.build as build_mod
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


def test_build_cache_invalidates_when_imported_module_changes(tmp_path: Path):
    src = tmp_path / "main.astra"
    dep = tmp_path / "helper.astra"
    out = tmp_path / "main.py"
    dep.write_text("fn helper() -> Int { return 1; }")
    src.write_text(
        """
import helper;
fn main() -> Int { return 0; }
"""
    )
    st1 = build(str(src), str(out), "py")
    st2 = build(str(src), str(out), "py")
    dep.write_text("fn helper() -> Int { return 2; }")
    st3 = build(str(src), str(out), "py")
    assert st1 in {"built", "cached"}
    assert st2 == "cached"
    assert st3 == "built"


def test_build_cache_invalidates_when_toolchain_stamp_changes(monkeypatch, tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.py"
    src.write_text("fn main() -> Int { return 0; }")
    monkeypatch.setattr(build_mod, "_toolchain_stamp", lambda: "toolchain-A")
    st1 = build(str(src), str(out), "py")
    st2 = build(str(src), str(out), "py")
    monkeypatch.setattr(build_mod, "_toolchain_stamp", lambda: "toolchain-B")
    st3 = build(str(src), str(out), "py")
    assert st1 in {"built", "cached"}
    assert st2 == "cached"
    assert st3 == "built"


def test_build_strict_mode_does_not_reject_empty_blocks(tmp_path: Path):
    src = tmp_path / "strict.astra"
    out = tmp_path / "strict.py"
    src.write_text(
        """
fn main() -> Int {
  if true {
  } else {
  }
  return 0;
}
"""
    )
    st = build(str(src), str(out), "py", strict=True)
    assert st in {"built", "cached"}


@pytest.mark.skipif(
    shutil.which("nasm") is None or (shutil.which("cc") is None and shutil.which("ld") is None),
    reason="native target requires nasm and a linker (cc/ld)",
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
    shutil.which("nasm") is None or (shutil.which("cc") is None and shutil.which("ld") is None),
    reason="native target requires nasm and a linker (cc/ld)",
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
    shutil.which("nasm") is None or (shutil.which("cc") is None and shutil.which("ld") is None),
    reason="native target requires nasm and a linker (cc/ld)",
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
    shutil.which("nasm") is None or (shutil.which("cc") is None and shutil.which("ld") is None),
    reason="native target requires nasm and a linker (cc/ld)",
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
    shutil.which("nasm") is None or (shutil.which("cc") is None and shutil.which("ld") is None),
    reason="native target requires nasm and a linker (cc/ld)",
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
    shutil.which("nasm") is None or (shutil.which("cc") is None and shutil.which("ld") is None),
    reason="native target requires nasm and a linker (cc/ld)",
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


@pytest.mark.skipif(
    shutil.which("nasm") is None or (shutil.which("cc") is None and shutil.which("ld") is None),
    reason="native target requires nasm and a linker (cc/ld)",
)
def test_build_native_supports_i128_hard_ops_with_runtime_helpers(tmp_path: Path):
    src = tmp_path / "i128.astra"
    out = tmp_path / "i128.exe"
    src.write_text(
        """
fn main() -> Int {
  let a: i128 = 20 as i128;
  let b: i128 = 3 as i128;
  let m: i128 = a * b;
  let d: i128 = a / b;
  let r: i128 = a % b;
  return (m as Int) + (d as Int) + (r as Int);
}
"""
    )
    st = build(str(src), str(out), "native", profile="debug", overflow="trap")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 68


def test_resolve_overflow_mode_profile_defaults():
    assert build_mod._resolve_overflow_mode("debug", "debug", check=False) == "trap"
    assert build_mod._resolve_overflow_mode("release", "debug", check=False) == "wrap"
    assert build_mod._resolve_overflow_mode("debug", "debug", check=True) == "trap"
    assert build_mod._resolve_overflow_mode("release", "trap", check=False) == "trap"
    assert build_mod._resolve_overflow_mode("debug", "wrap", check=False) == "wrap"


def test_build_cache_key_includes_profile_and_overflow(tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.py"
    src.write_text("fn main() -> Int { return 0; }")
    st1 = build(str(src), str(out), "py", profile="debug", overflow="debug")
    st2 = build(str(src), str(out), "py", profile="debug", overflow="debug")
    st3 = build(str(src), str(out), "py", profile="release", overflow="debug")
    st4 = build(str(src), str(out), "py", profile="release", overflow="debug")
    st5 = build(str(src), str(out), "py", profile="release", overflow="trap")
    assert st1 in {"built", "cached"}
    assert st2 == "cached"
    assert st3 == "built"
    assert st4 == "cached"
    assert st5 == "built"
