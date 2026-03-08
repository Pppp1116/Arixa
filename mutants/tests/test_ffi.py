import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from astra.ast import ExternFnDecl
from astra.build import build
from astra.codegen import to_python
from astra.llvm_codegen import to_llvm_ir
from astra.parser import ParseError, parse
from astra.semantic import analyze


def test_parse_extern_decl_shape():
    src = "extern fn foo(x i32) i32;"
    prog = parse(src)
    ext = prog.items[0]
    assert isinstance(ext, ExternFnDecl)
    assert ext.name == "foo"
    assert ext.params == [("x", "i32")]
    assert ext.ret == "i32"
    assert not ext.is_variadic
    assert ext.link_libs == []


def test_parse_variadic_extern_decl():
    src = 'extern fn printf(fmt *u8, ...) i32;'
    prog = parse(src)
    ext = prog.items[0]
    assert isinstance(ext, ExternFnDecl)
    assert ext.params == [("fmt", "*u8")]
    assert ext.is_variadic


def test_parse_link_attribute_on_extern():
    src = '@link("SDL2") extern fn SDL_Init(flags u32) i32;'
    prog = parse(src)
    ext = prog.items[0]
    assert isinstance(ext, ExternFnDecl)
    assert ext.link_libs == ["SDL2"]


def test_parse_multiple_link_attributes():
    src = '@link("SDL2") @link("SDL2main") extern fn SDL_Init(flags u32) i32;'
    prog = parse(src)
    ext = prog.items[0]
    assert isinstance(ext, ExternFnDecl)
    assert ext.link_libs == ["SDL2", "SDL2main"]


def test_semantic_extern_symbol_is_callable():
    src = "extern fn foo(x i32) i32; fn main() Int{ return foo(2i32); }"
    prog = parse(src)
    analyze(prog)


def test_semantic_extern_with_body_is_parse_error():
    src = "extern fn foo() i32{ return 1i32; }"
    with pytest.raises(ParseError):
        parse(src)


def test_semantic_extern_inside_function_is_parse_error():
    src = "fn main() Int{ extern fn foo() i32; return 0; }"
    with pytest.raises(ParseError, match="only allowed at module scope"):
        parse(src)


def test_llvm_codegen_emits_declare_for_extern():
    src = "extern fn foo(x i32) i32; fn main() Int{ return foo(1i32); }"
    prog = parse(src)
    ir = to_llvm_ir(prog, filename="<mem>")
    assert "declare signext i32 @foo(i32 signext)" in ir
    assert "define i32 @foo(" not in ir


def test_python_codegen_emits_ctypes_bindings():
    src = '@link("SDL2") extern fn SDL_Init(flags u32) i32; fn main() Int{ return 0; }'
    prog = parse(src)
    analyze(prog)
    py = to_python(prog)
    assert "_astra_load_lib" in py
    assert "_astra_load_first_lib" in py
    assert "ctypes.c_int32" in py
    assert "ctypes.c_uint32" in py


@pytest.mark.skipif(shutil.which("clang") is None, reason="native target requires clang")
def test_native_build_can_link_external_c_abi_library(tmp_path: Path, monkeypatch):
    c_file = tmp_path / "calcffi.c"
    so_file = tmp_path / "libcalcffi.so"
    c_file.write_text("int c_add7(int x) { return x + 7; }\n")
    cp = subprocess.run(["clang", "-shared", "-fPIC", str(c_file), "-o", str(so_file)], capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr or cp.stdout

    src = tmp_path / "main.astra"
    out = tmp_path / "app"
    src.write_text('@link("calcffi") extern fn c_add7(x i32) i32;\nfn main() Int{ return c_add7(5i32); }\n')

    old_library_path = os.environ.get("LIBRARY_PATH", "")
    old_ld_library_path = os.environ.get("LD_LIBRARY_PATH", "")
    monkeypatch.setenv("LIBRARY_PATH", f"{tmp_path}{os.pathsep}{old_library_path}" if old_library_path else str(tmp_path))
    monkeypatch.setenv("LD_LIBRARY_PATH", f"{tmp_path}{os.pathsep}{old_ld_library_path}" if old_ld_library_path else str(tmp_path))

    state = build(str(src), str(out), "native")
    assert state in {"built", "cached"}
    run = subprocess.run([str(out)], env=os.environ.copy())
    assert run.returncode == 12
