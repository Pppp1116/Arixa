import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import astra.build as build_mod
from astra.asm_assert import assert_valid_llvm_ir
from astra.build import build
from astra.semantic import SemanticError


def test_build_py(tmp_path: Path):
    src = tmp_path / 'a.astra'
    src.write_text('fn main() Int{ print("ok"); return 0; }')
    out = tmp_path / 'a.py'
    st = build(str(src), str(out), 'py')
    assert st in {'built','cached'}
    assert out.exists()


def test_build_py_expands_serde_derives(tmp_path: Path):
    src = tmp_path / "derive_serde.astra"
    out = tmp_path / "derive_serde.py"
    src.write_text(
        """
@derive(Serialize, Deserialize)
struct User {
  name String,
  age Int,
}

fn main() Int{
  u = User("ana", 7);
  txt = serialize_User(u);
  rt = deserialize_User(txt);
  v = rt as User;
  return v.age;
}
"""
    )
    st = build(str(src), str(out), "py")
    assert st in {"built", "cached"}
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True)
    assert cp.returncode == 7


def test_build_emit_ir(tmp_path: Path):
    src = tmp_path / "a.astra"
    src.write_text("fn main() Int{ x = 1 + 2; return x; }")
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
    src.write_text("fn main() Int{ return 0; }")
    # Simulate an environment without clang even if CI provides it.
    monkeypatch.setattr(build_mod, "shutil", shutil)
    monkeypatch.setattr(build_mod.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError) as excinfo:
        build(str(src), str(out), "native")
    msg = str(excinfo.value)
    assert msg.startswith("CODEGEN ")


def test_build_native_accepts_sanitizer_flag(monkeypatch, tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.exe"
    src.write_text("fn main() Int{ return 0; }")
    seen: list[list[str]] = []

    def fake_run(cmd, capture_output=True, text=True):
        seen.append(list(cmd))
        if "-o" in cmd:
            out_idx = cmd.index("-o") + 1
            Path(cmd[out_idx]).write_text("")
        class CP:
            returncode = 0
            stderr = ""
            stdout = ""
        return CP()

    monkeypatch.setattr(build_mod.shutil, "which", lambda _: "/usr/bin/clang")
    monkeypatch.setattr(build_mod.subprocess, "run", fake_run)
    st = build(str(src), str(out), "native", sanitize="address")
    assert st in {"built", "cached"}
    assert any("-fsanitize=address" in arg for cmd in seen for arg in cmd)


def test_build_rejects_sanitizer_for_non_native_targets(tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.py"
    src.write_text("fn main() Int{ return 0; }")
    with pytest.raises(RuntimeError) as excinfo:
        build(str(src), str(out), "py", sanitize="address")
    assert "sanitizer requires --target native" in str(excinfo.value)


def test_build_cache_invalidates_when_imported_module_changes(tmp_path: Path):
    src = tmp_path / "main.astra"
    dep = tmp_path / "helper.arixa"
    out = tmp_path / "main.py"
    dep.write_text("fn helper() Int{ return 1; }")
    src.write_text(
        """
import helper;
fn main() Int{ return 0; }
"""
    )
    st1 = build(str(src), str(out), "py")
    st2 = build(str(src), str(out), "py")
    dep.write_text("fn helper() Int{ return 2; }")
    st3 = build(str(src), str(out), "py")
    assert st1 in {"built", "cached"}
    assert st2 == "cached"
    assert st3 == "built"


def test_build_cache_invalidates_when_string_imported_module_changes(tmp_path: Path):
    src = tmp_path / "main.astra"
    dep_dir = tmp_path / "deps"
    dep = dep_dir / "helper.arixa"
    out = tmp_path / "main.py"
    dep_dir.mkdir()
    dep.write_text("fn helper() Int{ return 1; }")
    src.write_text(
        """
import "deps/helper";
fn main() Int{ return 0; }
"""
    )
    st1 = build(str(src), str(out), "py")
    st2 = build(str(src), str(out), "py")
    dep.write_text("fn helper() Int{ return 2; }")
    st3 = build(str(src), str(out), "py")
    assert st1 in {"built", "cached"}
    assert st2 == "cached"
    assert st3 == "built"


def test_build_py_can_call_functions_from_imported_module(tmp_path: Path):
    src = tmp_path / "main.astra"
    dep = tmp_path / "helper.arixa"
    out = tmp_path / "main.py"
    dep.write_text("fn helper(v Int) Int{ return v + 2; }")
    src.write_text(
        """
import helper;
fn main() Int{
  return helper(5);
}
"""
    )
    st = build(str(src), str(out), "py")
    assert st in {"built", "cached"}
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True)
    assert cp.returncode == 7


def test_build_cache_invalidates_when_toolchain_stamp_changes(monkeypatch, tmp_path: Path):
    src = tmp_path / "main.astra"
    out = tmp_path / "main.py"
    src.write_text("fn main() Int{ return 0; }")
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
fn main() Int{
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
fn main() Int{
  x = 2;
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


def test_build_strict_mode_accepts_try_operator(tmp_path: Path):
    src = tmp_path / "strict_try.astra"
    out = tmp_path / "strict_try.py"
    src.write_text(
        """
fn helper(v Int?) Int?{
  x = v!;
  return x;
}
fn main() Int{
  return helper(3) ?? 0;
}
"""
    )
    st = build(str(src), str(out), "py", strict=True)
    assert st in {"built", "cached"}


def test_build_strict_mode_accepts_union_try_operator(tmp_path: Path):
    src = tmp_path / "strict_try_union.astra"
    out = tmp_path / "strict_try_union.py"
    src.write_text(
        """
fn helper(v Int) Int | none{
  if v > 0 { return v; } else {}
  return none;
}
fn wrap(v Int) Int | none{
  x = helper(v)!;
  return x + 1;
}
fn main() Int{
  _ = wrap(1);
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
    src.write_text("fn main() Int{ return 7; }")
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
fn main() Int{
  print("ok");
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
fn main() Int{
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
def test_build_native_freestanding_runtime_free_program_links_without_runtime(tmp_path: Path):
    src = tmp_path / "k.astra"
    out = tmp_path / "k.exe"
    src.write_text(
        """
fn _start() Int{
  x = 40 + 2;
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
fn _start() Int{
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
    src.write_text("fn kernel() Int{ return 0; }")
    with pytest.raises(SemanticError, match=r"missing _start\(\)"):
        build(str(src), str(out), "native", freestanding=True)


def test_build_exe_requires_main_for_hosted_targets(tmp_path: Path):
    src = tmp_path / "mod.astra"
    out = tmp_path / "mod.py"
    src.write_text("fn helper() Int{ return 1; }")
    with pytest.raises(SemanticError, match=r"missing main\(\)"):
        build(str(src), str(out), "py", kind="exe")


def test_build_kind_lib_allows_missing_main_and_skips_python_entrypoint(tmp_path: Path):
    src = tmp_path / "lib.astra"
    out = tmp_path / "lib.py"
    src.write_text("fn helper() Int{ return 1; }")
    st = build(str(src), str(out), "py", kind="lib")
    assert st in {"built", "cached"}
    text = out.read_text()
    assert "if __name__ == '__main__':" not in text
    assert "def helper(" in text


def test_build_kind_lib_freestanding_allows_missing_start(tmp_path: Path):
    src = tmp_path / "lib_fs.astra"
    out = tmp_path / "lib_fs.ll"
    src.write_text("fn helper() Int{ return 1; }")
    st = build(str(src), str(out), "llvm", kind="lib", freestanding=True)
    assert st in {"built", "cached"}
    assert out.exists()


def test_build_freestanding_rejects_external_host_symbols(tmp_path: Path):
    src = tmp_path / "host_dep.astra"
    out = tmp_path / "host_dep.ll"
    src.write_text(
        """
extern c fn host() Int;
fn _start() Int{
  return host();
}
"""
    )
    with pytest.raises(RuntimeError, match="freestanding build cannot depend on external host symbols: host"):
        build(str(src), str(out), "llvm", freestanding=True)


def test_build_freestanding_allows_platform_hook_symbols(tmp_path: Path):
    src = tmp_path / "fs_hook.astra"
    out = tmp_path / "fs_hook.ll"
    src.write_text(
        """
extern c fn __fs_tick_now_impl() Int;
fn _start() Int{
  return __fs_tick_now_impl();
}
"""
    )
    st = build(str(src), str(out), "llvm", freestanding=True)
    assert st in {"built", "cached"}
    text = out.read_text()
    assert "__fs_tick_now_impl" in text


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_freestanding_platform_hook_symbol_links_with_default_hooks(tmp_path: Path):
    src = tmp_path / "fs_hook_native.astra"
    out = tmp_path / "fs_hook_native.exe"
    src.write_text(
        """
extern c fn __fs_tick_now_impl() Int;
fn _start() Int{
  return __fs_tick_now_impl();
}
"""
    )
    st = build(str(src), str(out), "native", freestanding=True)
    assert st in {"built", "cached"}
    assert out.exists()
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    assert cp.returncode == 0


def test_freestanding_hooks_source_includes_default_platform_hooks() -> None:
    text = build_mod._freestanding_hooks_source()
    assert "__fs_volatile_read8_impl" in text
    assert "__fs_volatile_write64_impl" in text
    assert "volatile uint8_t" in text
    assert "volatile uint64_t" in text
    assert "__fs_tick_now_impl" in text
    assert "__fs_panic_with_code_impl" in text


def test_freestanding_entry_source_includes_riscv64_exit_path() -> None:
    text = build_mod._freestanding_entry_source()
    assert "__riscv" in text
    assert "li a7, 93" in text
    assert "__astra_entry" in text


def test_build_freestanding_supports_vec_builtins_without_runtime_symbols(tmp_path: Path):
    src = tmp_path / "vec_fs.astra"
    out = tmp_path / "vec_fs.ll"
    src.write_text(
        """
fn _start() Int{
  mut v: Vec<Int> = vec_new() as Vec<Int>;
  vec_push(v, 40);
  vec_push(v, 2);
  got: Int? = vec_get(v, 1);
  vec_set(v, 0, 1);
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
fn _start() Int{
  p = Pair(2, 3);
  xs = vec_from([7, 11, 13]);
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
@pytest.mark.skipif(
    True,
    reason="runtime environment dependent coverage test",
)
def test_build_native_supports_non_runtime_builtins(tmp_path: Path):
    src = tmp_path / "builtins.astra"
    out = tmp_path / "builtins.exe"
    src.write_text(
        """
fn main() Int{
  read_file("missing.txt");
  cwd();
  now_unix();
  monotonic_ms();
  len(1);
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
fn main() Int{
  s = "a" + "b";
  t = s + "c";
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
fn main() Int{
  m = map_new();
  map_set(m, "k", 7);
  xs = list_new();
  list_push(xs, 1);
  list_push(xs, 2);
  map_set(m, "xs", xs);
  js = to_json(m);
  rt = from_json(js);
  k = map_get(rt, "k") as Int;
  ys = map_get(rt, "xs");
  y1 = list_get(ys, 1) as Int;
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
fn main() Int{
  a = [10, 20, 30][1];
  b: Int? = [1, 2, 3].get(2);
  c: Int? = [1, 2].get(9);
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
fn main() Int{
  p = P(1, 2 as u8);
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
fn main() Int{
  x: u8 = 1 as u8;
  s: u8 = 8 as u8;
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
fn main() Int{
  mut h = Header(3u4, 5u3, 1u1, 9u8);
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
fn main() Int{
  mut w = Wide(1u7, 5u128, 1u1);
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
fn main() Int{
  mut w = Wide(1u7, 5u128, 1u1);
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
    shutil.which("clang") is None or sys.platform.startswith("win"),
    reason="native TCP runtime test requires clang and POSIX sockets",
)
def test_build_native_tcp_runtime_roundtrip(tmp_path: Path):
    ready = threading.Event()
    port_box: list[int] = []

    def _server() -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port_box.append(int(srv.getsockname()[1]))
        ready.set()
        conn, _ = srv.accept()
        try:
            _ = conn.recv(16)
            conn.sendall(b"pong")
        finally:
            conn.close()
            srv.close()

    th = threading.Thread(target=_server, daemon=True)
    th.start()
    assert ready.wait(timeout=3.0)
    assert port_box
    port = port_box[0]

    src = tmp_path / "tcp_roundtrip.astra"
    out = tmp_path / "tcp_roundtrip.exe"
    src.write_text(
        f"""
fn main() Int{{
  conn = tcp_connect("127.0.0.1:{port}");
  if conn < 0 {{
    return 100;
  }}
  sent = tcp_send(conn, "ping");
  recv_len = len(tcp_recv(conn, 4));
  closed = tcp_close(conn);
  return sent + recv_len + closed;
}}
"""
    )
    st = build(str(src), str(out), "native")
    assert st in {"built", "cached"}
    cp = subprocess.run([str(out)], capture_output=True, text=True)
    th.join(timeout=3.0)
    assert cp.returncode == 8


@pytest.mark.skipif(
    shutil.which("clang") is None,
    reason="native target requires clang",
)
def test_build_native_supports_float_mod(tmp_path: Path):
    src = tmp_path / "fmod.astra"
    out = tmp_path / "fmod.exe"
    src.write_text(
        """
fn main() Int{
  mut x = 7.5;
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
fn main() Int{
  a: i128 = 20 as i128;
  b: i128 = 3 as i128;
  m: i128 = a * b;
  d: i128 = a / b;
  r: i128 = a % b;
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
    src.write_text("fn main() Int{ return 0; }")
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


def test_build_python_profile_controls_debug_assert_emission(tmp_path: Path):
    src = tmp_path / "asserts.astra"
    out_debug = tmp_path / "asserts_debug.py"
    out_release = tmp_path / "asserts_release.py"
    src.write_text("fn main() Int{ debug_assert(true); return 0; }")
    assert build(str(src), str(out_debug), "py", profile="debug") in {"built", "cached"}
    assert build(str(src), str(out_release), "py", profile="release") in {"built", "cached"}
    debug_text = out_debug.read_text()
    release_text = out_release.read_text()
    assert "_ASTRA_PROFILE = 'debug'" in debug_text
    assert "_ASTRA_PROFILE = 'release'" in release_text
    assert "debug_assert_(True)" in debug_text
    assert "debug_assert_(True)" not in release_text
