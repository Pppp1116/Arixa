from pathlib import Path

from astra.build import build
from astra.codegen import to_python, to_x86_64
from astra.parser import parse
from astra.semantic import SemanticError, analyze


def test_spawn_builtin_semantic_ok():
    prog = parse("fn worker(x Int) -> Int { return x; } fn main() -> Int { let t = spawn(worker, 1); return join(t); }")
    analyze(prog)


def test_memory_builtins_semantic_ok():
    prog = parse("fn main() -> Int { let p = alloc(32); free(p); return 0; }")
    analyze(prog)


def test_codegen_includes_thread_runtime_helpers():
    py = to_python(parse("fn main() -> Int { return 0; }"))
    assert "def spawn(fn, *a):" in py
    assert "def join(tid):" in py


def test_codegen_includes_memory_runtime_helpers():
    py = to_python(parse("fn main() -> Int { return 0; }"))
    assert "def alloc(n):" in py
    assert "def free(ptr):" in py


def test_x86_64_assembly_matches_expected_stub():
    asm = to_x86_64(parse("fn main() -> Int { return 0; }"))
    expected = """global _start
section .text
_start:
  mov rax, 60
  mov rdi, 0
  syscall
"""
    assert asm == expected


def test_x86_64_build_writes_expected_assembly(tmp_path: Path):
    src = tmp_path / "prog.astra"
    out = tmp_path / "prog.s"
    src.write_text("fn main() -> Int { return 0; }")
    build(str(src), str(out), "x86_64")
    assert out.read_text() == to_x86_64(parse(src.read_text()))


def test_join_of_unknown_tid_allowed_semantically():
    prog = parse("fn main() -> Int { return join(999); }")
    analyze(prog)


def test_missing_main_is_semantic_error():
    prog = parse("fn helper() -> Int { return 1; }")
    try:
        analyze(prog)
        assert False
    except SemanticError:
        assert True


def test_selfhost_source_compiles_to_python(tmp_path: Path):
    out = tmp_path / "selfhost.py"
    state = build("selfhost/compiler.astra", str(out), "py")
    assert state in {"built", "cached"}
    text = out.read_text()
    assert "def compile(input, output):" in text


def test_thread_calls_emit_in_python_output():
    src = "fn worker(x Int) -> Int { return x; } fn main() -> Int { let t = spawn(worker, 3); return join(t); }"
    py = to_python(parse(src))
    assert "spawn(worker, 3)" in py
    assert "join(t)" in py
