import os
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARIXA_BIN = os.path.join(REPO_ROOT, ".venv", "bin", "arixa")


def _get_arixa_command() -> str:
    if os.path.exists(ARIXA_BIN):
        return ARIXA_BIN
    path_cmd = shutil.which("arixa")
    if path_cmd:
        return path_cmd
    pytest.skip("arixa CLI binary not available in .venv/bin or PATH")


def _compile_and_run(source: str) -> tuple[int, str, str]:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".arixa", delete=False) as f:
        f.write(source)
        src = f.name
    out = src.replace(".arixa", ".py")
    try:
        build = subprocess.run(
            [_get_arixa_command(), "build", "-o", out, "--target", "py", src],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        if build.returncode != 0:
            return build.returncode, build.stdout, build.stderr
        run = subprocess.run(
            [sys.executable, out],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        return run.returncode, run.stdout, run.stderr
    finally:
        if os.path.exists(src):
            os.unlink(src)
        if os.path.exists(out):
            os.unlink(out)


def test_stdlib_runtime_data_bytes_mem_core_algorithm() -> None:
    src = """
import std.algorithm as algorithm;
import std.core as core;
import std.mem as mem;
import std.bytes as bytes;
import std.data as data;

fn main() Int {
  xs = vec_new() as Vec<Int>;
  vec_push(xs, 1);
  vec_push(xs, 2);
  vec_push(xs, 2);
  assert algorithm.sum_int(&xs) == 5;
  assert algorithm.count_int(&xs, 2) == 2;
  assert algorithm.is_sorted_int(&xs);

  assert core.saturating_add(maxVal(Int), 1) == maxVal(Int);
  assert core.saturating_sub(minVal(Int), 1) == minVal(Int);

  bs = vec_from([1, 2, 3, 2]) as Bytes;
  assert bytes.count_byte(bs, 2 as u8) == 2;
  assert bytes.index_of_byte(bs, 3 as u8) == 2;

  parts = vec_from([vec_from([65]) as Bytes, vec_from([66]) as Bytes]);
  joined = bytes.join(parts, vec_from([45]) as Bytes);
  assert bytes.len(joined) == 3;

  dst = vec_from([0, 0, 0, 0]) as Bytes;
  copied = mem.copy_bytes(dst, bs);
  assert copied == 4;
  assert mem.bytes_equal(dst, bs);

  st = data.stack_new();
  data.stack_push(st, 9);
  popped = data.stack_pop(st);
  assert popped != none && (popped as Int) == 9;

  rb = data.ring_buffer_new(2);
  assert data.ring_buffer_is_empty(rb);
  push_ok = data.ring_buffer_push(rb, 7);
  assert push_ok != none;
  assert data.ring_buffer_len(rb) == 1;
  got = data.ring_buffer_pop(rb);
  assert got != none && (got as Int) == 7;
  assert data.ring_buffer_is_empty(rb);
  return 0;
}
"""
    code, out, err = _compile_and_run(src)
    assert code == 0, f"stdout={out}\nstderr={err}"


def test_stdlib_runtime_str_encoding_and_io() -> None:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        path = f.name.replace("\\", "\\\\")
    try:
        src = f"""
import std.str;
import std.encoding;
import std.bytes as bytes;
import std.io;

fn main() Int {{
  assert str.starts_with("abcdef", "abc");
  assert str.ends_with("abcdef", "def");
  assert str.parse_int_checked("123") != none;
  assert str.parse_int_checked("abc") == none;

  b = encoding.utf8_encode("Hello");
  decoded = encoding.utf8_decode(b);
  match decoded {{
    String => {{
      assert str.length(decoded as String) == 5;
    }},
    Utf8Error => {{
      assert false;
    }}
  }}

  hex_text = encoding.hex_encode_upper(b);
  parsed_hex = encoding.hex_decode(hex_text);
  match parsed_hex {{
    Bytes => {{
      assert bytes.len(parsed_hex as Bytes) == 5;
    }},
    DecodeError => {{
      assert false;
    }}
  }}

  b64 = encoding.base64_encode(b);
  parsed_b64 = encoding.base64_decode(b64);
  match parsed_b64 {{
    Bytes => {{
      assert bytes.len(parsed_b64 as Bytes) == 5;
    }},
    DecodeError => {{
      assert false;
    }}
  }}

  io.write("{path}", "line1\\nline2");
  lines = io.read_lines("{path}");
  assert vec_len(lines) >= 2;
  io.append_line("{path}", "line3");
  return 0;
}}
"""
        code, out, err = _compile_and_run(src)
        assert code == 0, f"stdout={out}\nstderr={err}"
    finally:
        if os.path.exists(path):
            os.unlink(path)


def test_stdlib_runtime_string_format_and_print_helpers() -> None:
    src = """
import std.str;
import std.io;

fn main() Int {
  a = "hello" as Any;
  assert str.format(a) == "hello";
  assert str.format(123) == "123";
  assert str.to_string(true) == "true";

  io.print("k");
  io.print(1);
  io.print(true);
  io.print(2.5);
  return 0;
}
"""
    code, out, err = _compile_and_run(src)
    assert code == 0, f"stdout={out}\nstderr={err}"
