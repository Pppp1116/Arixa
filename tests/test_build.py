import shutil
import subprocess
from pathlib import Path

import pytest

import astra.build as build_mod
from astra.asm_assert import assert_valid_llvm_ir
from astra.build import build
from astra.semantic import SemanticError


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
    ir = tmp_path / "a.ll"
    st = build(str(src), str(out), "py", emit_ir=str(ir))
    assert st in {"built", "cached"}
    assert ir.exists()
    text = ir.read_text()
    assert "define i32 @main()" in text
    assert "astra_run_py" not in text


def test_native_missing_clang_reports_codegen_error(monkeypatch, tmp_path: Path):
    src = tmp_path / "no_clang.astra"
    out = tmp_path / "no_clang.exe"
    src.write_text("fn main() -> Int { return 0; }")
    # Simulate an environment without clang even if CI provides it.
    monkeypatch.setattr(build_mod, "shutil", shutil)
    monkeypatch.setattr(build_mod.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError) as excinfo:
        build(str(src), str(out), "native")
    msg = str(excinfo.value)
    assert msg.startswith("CODEGEN ")


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


def test_build_cache_invalidates_when_string_imported_module_changes(tmp_path: Path):
    src = tmp_path / "main.astra"
    dep_dir = tmp_path / "deps"
    dep = dep_dir / "helper.astra"
    out = tmp_path / "main.py"
    dep_dir.mkdir()
    dep.write_text("fn helper() -> Int { return 1; }")
    src.write_text(
        """
import "deps/helper";
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


def test_build_strict_mode_accepts_wildcard_pattern_in_match(tmp_path: Path):
    src = tmp_path / "strict_wildcard.astra"
    out = tmp_path / "strict_wildcard.py"
    src.write_text(
        """
fn main() -> Int {
  let x = 2;
  match x {
    1 => { return 1; }
    _ => { return 0; }
  }
  return 0;
}
"""
    )
    st = build(str(src), str(out), "py", strict=True)
    assert st in {"built", "cached"}


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
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
    shutil.which("clang") is None,
    reason="native target requires clang",
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
    shutil.which("clang") is None,
    reason="native target requires clang",
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
    shutil.which("clang") is None,
    reason="native target requires clang",
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
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_freestanding_runtime_free_program_links_without_runtime(tmp_path: Path):
    src = tmp_path / "k.astra"
    out = tmp_path / "k.exe"
    src.write_text(
        """
fn _start() -> Int {
  let x = 40 + 2;
  return x;
}
"""
    )
    st = build(str(src), str(out), "native", freestanding=True)
    assert st in {"built", "cached"}
    assert out.exists()
    assert out.stat().st_mode & 0o111


def test_build_freestanding_rejects_runtime_builtins(tmp_path: Path):
    src = tmp_path / "bad.astra"
    out = tmp_path / "bad.ll"
    src.write_text(
        """
fn _start() -> Int {
  print("x");
  return 0;
}
"""
    )
    with pytest.raises(SemanticError, match="freestanding mode forbids builtin print"):
        build(str(src), str(out), "llvm", freestanding=True)


def test_build_native_freestanding_requires_start_symbol(tmp_path: Path):
    src = tmp_path / "bad_start.astra"
    out = tmp_path / "bad_start.exe"
    src.write_text("fn kernel() -> Int { return 0; }")
    with pytest.raises(RuntimeError, match=r"freestanding native target requires fn _start\(\)"):
        build(str(src), str(out), "native", freestanding=True)


def test_build_freestanding_rejects_external_host_symbols(tmp_path: Path):
    src = tmp_path / "host_dep.astra"
    out = tmp_path / "host_dep.ll"
    src.write_text(
        """
extern c fn host() -> Int;
fn _start() -> Int {
  return host();
}
"""
    )
    with pytest.raises(RuntimeError, match="freestanding build cannot depend on external host symbols: host"):
        build(str(src), str(out), "llvm", freestanding=True)


def test_build_freestanding_supports_vec_builtins_without_runtime_symbols(tmp_path: Path):
    src = tmp_path / "vec_fs.astra"
    out = tmp_path / "vec_fs.ll"
    src.write_text(
        """
fn _start() -> Int {
  let mut v: Vec<Int> = vec_new() as Vec<Int>;
  drop vec_push(v, 40);
  drop vec_push(v, 2);
  let got: Option<Int> = vec_get(v, 1);
  drop vec_set(v, 0, 1);
  return vec_len(v) + (got ?? 0);
}
"""
    )
    st = build(str(src), str(out), "llvm", freestanding=True)
    assert st in {"built", "cached"}
    text = out.read_text()
    assert "@astra_" not in text
    assert "__astra_fs_heap" in text


def test_build_freestanding_supports_array_literals_and_struct_constructors(tmp_path: Path):
    src = tmp_path / "alloc_fs.astra"
    out = tmp_path / "alloc_fs.ll"
    src.write_text(
        """
struct Pair { a Int, b Int }
fn _start() -> Int {
  let p = Pair(2, 3);
  let xs = vec_from([7, 11, 13]);
  return p.a + p.b + (vec_get(xs, 1) ?? 0);
}
"""
    )
    st = build(str(src), str(out), "llvm", freestanding=True)
    assert st in {"built", "cached"}
    text = out.read_text()
    assert "@astra_" not in text
    assert "__astra_fs_heap" in text


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
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
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_supports_string_concatenation(tmp_path: Path):
    src = tmp_path / "concat.astra"
    out = tmp_path / "concat.exe"
    src.write_text(
        """
fn main() -> Int {
  let s = "a" + "b";
  let t = s + "c";
  return len(t);
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 3


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_json_roundtrip_keeps_map_and_list_shapes(tmp_path: Path):
    src = tmp_path / "json_roundtrip.astra"
    out = tmp_path / "json_roundtrip.exe"
    src.write_text(
        """
fn main() -> Int {
  let m = map_new();
  map_set(m, "k", 7);
  let xs = list_new();
  list_push(xs, 1);
  list_push(xs, 2);
  map_set(m, "xs", xs);
  let js = to_json(m);
  let rt = from_json(js);
  let k = map_get(rt, "k") as Int;
  let ys = map_get(rt, "xs");
  let y1 = list_get(ys, 1) as Int;
  return k + y1;
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 9


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_supports_array_index_get_and_coalesce(tmp_path: Path):
    src = tmp_path / "array_ops.astra"
    out = tmp_path / "array_ops.exe"
    src.write_text(
        """
fn main() -> Int {
  let a = [10, 20, 30][1];
  let b: Option<Int> = [1, 2, 3].get(2);
  let c: Option<Int> = [1, 2].get(9);
  return a + (b ?? 0) + (c ?? 7);
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 30


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_supports_layout_queries(tmp_path: Path):
    src = tmp_path / "layout.astra"
    out = tmp_path / "layout.exe"
    src.write_text(
        """
struct P { a Int, b u8 }
fn main() -> Int {
  let p = P(1, 2 as u8);
  return sizeof(P) + alignof(P) + size_of(p.a) + align_of(p.b);
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 33


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_shift_out_of_range_traps(tmp_path: Path):
    src = tmp_path / "shift_trap.astra"
    out = tmp_path / "shift_trap.exe"
    src.write_text(
        """
fn main() -> Int {
  let x: u8 = 1 as u8;
  let s: u8 = 8 as u8;
  return (x << s) as Int;
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode != 0


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_supports_packed_struct_bitfield_ops(tmp_path: Path):
    src = tmp_path / "packed.astra"
    out = tmp_path / "packed.exe"
    src.write_text(
        """
@packed struct Header { a: u4, b: u3, c: u1, d: u8 }
fn main() -> Int {
  let mut h = Header(3u4, 5u3, 1u1, 9u8);
  h.a += 1u4;
  h.d = 7u8;
  return (h.a as Int) + (h.b as Int) + (h.c as Int) + (h.d as Int);
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 17


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_supports_packed_struct_fields_above_64_bits(tmp_path: Path):
    src = tmp_path / "packed_wide.astra"
    out = tmp_path / "packed_wide.exe"
    src.write_text(
        """
@packed struct Wide {
  pad: u7,
  big: u128,
  tail: u1,
}
fn main() -> Int {
  let mut w = Wide(1u7, 5u128, 1u1);
  w.big += 2u128;
  w.big <<= 1u128;
  return (w.pad as Int) + (w.big as Int) + (w.tail as Int);
}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 16


def test_build_llvm_supports_packed_struct_fields_above_64_bits(tmp_path: Path):
    src = tmp_path / "packed_wide_llvm.astra"
    out = tmp_path / "packed_wide_llvm.ll"
    src.write_text(
        """
@packed struct Wide {
  pad: u7,
  big: u128,
  tail: u1,
}
fn main() -> Int {
  let mut w = Wide(1u7, 5u128, 1u1);
  w.big += 2u128;
  w.big <<= 1u128;
  return (w.pad as Int) + (w.big as Int) + (w.tail as Int);
}
"""
    )
    st = build(str(src), str(out), "llvm")
    assert st in {"built", "cached"}
    text = out.read_text()
    assert_valid_llvm_ir(text, workdir=tmp_path)
    assert "i136" in text


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_supports_extended_runtime_builtins(tmp_path: Path):
    src = tmp_path / "runtime_ext.astra"
    out = tmp_path / "runtime_ext.exe"
    tmpf = tmp_path / "io.txt"
    src.write_text(
        f"""
fn worker(x: Int) -> Int {{ return x + 1; }}
fn main() -> Int {{
  drop args();
  drop arg(0);
  let t = spawn(worker, 1);
  let tj = join(t) as Int;

  let xs = list_new();
  drop list_push(xs, 11);
  drop list_push(xs, 22);
  let a = list_len(xs);
  let b = list_get(xs, 1) as Int;
  drop list_set(xs, 0, 5);

  let m = map_new();
  drop map_set(m, 7, 9);
  let mh = map_has(m, 7);
  let mg = map_get(m, 7) as Int;
  let mut bh = 0;
  if mh {{
    bh = 1;
  }}

  let js = to_json(123);
  let n = from_json(js) as Int;
  drop sha256(\"abc\");
  drop hmac_sha256(\"k\", \"v\");
  drop env_get(\"HOME\");
  drop cwd();

  let wf = write_file(\"{tmpf}\", \"x\");
  let rf = len(read_file(\"{tmpf}\"));
  let ex1 = file_exists(\"{tmpf}\") as Int;
  drop file_remove(\"{tmpf}\");
  let ex2 = file_exists(\"{tmpf}\") as Int;

  let tc = tcp_connect(\"127.0.0.1:1\");
  let ts = tcp_send(tc, \"x\");
  let tr = len(tcp_recv(tc, 8));
  let tcl = tcp_close(tc);

  let pr = proc_run(\"true\");
  drop now_unix();
  drop monotonic_ms();
  let sl = sleep_ms(1);

  return a + b + bh + mg + n + wf + rf + ex1 + ex2 + tj + tc + ts + tr + tcl + pr + sl;
}}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 160


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
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
    shutil.which("clang") is None,
    reason="native target requires clang",
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


def test_build_dce_prunes_unreachable_functions_and_imported_module_items(tmp_path: Path):
    src = tmp_path / "main.astra"
    dep = tmp_path / "helper.astra"
    out = tmp_path / "main.py"
    dep.write_text(
        """
fn used_from_dep() -> Int { return 7; }
fn unused_from_dep() -> Int { return 99; }
"""
    )
    src.write_text(
        """
import helper;
fn used_local() -> Int { return used_from_dep(); }
fn unused_local() -> Int { return 13; }
fn main() -> Int { return used_local(); }
"""
    )
    st = build(str(src), str(out), "py")
    assert st in {"built", "cached"}
    py = out.read_text()
    assert "def used_local(" in py
    assert "def used_from_dep(" in py
    assert "def unused_local(" not in py
    assert "def unused_from_dep(" not in py


def test_build_without_std_usage_does_not_emit_std_module_functions(tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.py"
    src.write_text('fn main() -> Int { print("hi"); return 0; }')
    st = build(str(src), str(out), "py")
    assert st in {"built", "cached"}
    py = out.read_text()
    assert "def digest_pair(" not in py
    assert "def hmac_sha256(" in py  # runtime builtin helper remains available


def test_build_dce_keeps_only_used_std_functions(tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.py"
    src.write_text(
        """
import std.math;
fn main() -> Int { return abs_int(-9); }
"""
    )
    st = build(str(src), str(out), "py")
    assert st in {"built", "cached"}
    py = out.read_text()
    assert "def abs_int(" in py
    assert "def min_int(" not in py
    assert "def max_int(" not in py
    assert "def clamp_int(" not in py
