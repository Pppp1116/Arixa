import subprocess
import sys
from pathlib import Path

from astra.asm_assert import assert_valid_x86_64_assembly
from astra.build import build
from astra.codegen import CodegenError, to_python, to_x86_64
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
    assert "def await_result(v):" in py


def test_codegen_includes_memory_runtime_helpers():
    py = to_python(parse("fn main() -> Int { return 0; }"))
    assert "def alloc(n):" in py
    assert "def free(ptr):" in py


def test_python_codegen_freestanding_has_no_auto_main():
    py = to_python(parse("fn kernel() -> Int { return 0; }"), freestanding=True)
    assert "if __name__ == '__main__':" not in py


def test_python_codegen_coalesce_operator():
    py = to_python(parse("fn main() -> Int { return none ?? 5; }"))
    assert "lambda __v:" in py
    assert "is not None else 5" in py


def test_defer_executes_on_return(tmp_path: Path):
    src = tmp_path / "d.astra"
    out = tmp_path / "d.py"
    src.write_text(
        """
fn main() -> Int {
  defer print("deferred");
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)], capture_output=True, text=True)
    assert cp.returncode == 0
    assert "deferred" in cp.stdout


def test_specialization_codegen_uses_most_specific_impl(tmp_path: Path):
    src = tmp_path / "spec.astra"
    out = tmp_path / "spec.py"
    src.write_text(
        """
impl fn sum(x T) -> T { return x; }
impl fn sum(x Int) -> Int { return x + 1; }
fn main() -> Int { return sum(1); }
"""
    )
    build(str(src), str(out), "py")
    cp = subprocess.run([sys.executable, str(out)])
    assert cp.returncode == 2


def test_x86_64_assembly_has_runtime_entry_and_main():
    asm = to_x86_64(parse("fn main() -> Int { return 0; }"))
    assert_valid_x86_64_assembly(asm)
    assert "global _start" in asm
    assert "_start:" in asm
    assert "call main" in asm
    assert "main:" in asm


def test_x86_64_build_writes_expected_assembly(tmp_path: Path):
    src = tmp_path / "prog.astra"
    out = tmp_path / "prog.s"
    src.write_text("fn main() -> Int { return 0; }")
    build(str(src), str(out), "x86_64")
    asm = out.read_text()
    assert_valid_x86_64_assembly(asm, workdir=tmp_path)
    assert asm == to_x86_64(parse(src.read_text()))


def test_x86_64_lowers_runtime_builtin_calls():
    prog = parse('fn main() -> Int { print("x"); let p = alloc(8); free(p); return 0; }')
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "extern astra_print_str" in asm
    assert "extern astra_alloc" in asm
    assert "extern astra_free" in asm
    assert "call astra_print_str" in asm
    assert "call astra_alloc" in asm
    assert "call astra_free" in asm


def test_x86_64_supports_structured_defer_for_calls():
    prog = parse("fn cleanup(x Int) -> Void { drop x; } fn main() -> Int { let x = 7; defer cleanup(x); return x; }")
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "defer_skip" in asm
    assert "call cleanup" in asm


def test_x86_64_supports_defer_non_call_expression():
    prog = parse("fn main() -> Int { defer 1; return 0; }")
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "defer_loop" in asm


def test_x86_64_supports_conditionals_and_loops():
    src = """
fn main() -> Int {
  let x = 0;
  while x < 3 {
    x += 1;
  }
  if x == 3 {
    return 7;
  }
  return 1;
}
"""
    asm = to_x86_64(parse(src))
    assert_valid_x86_64_assembly(asm)
    assert "while_begin" in asm
    assert "if_else" in asm


def test_x86_64_supports_more_than_six_call_arguments():
    src = """
fn sum(a Int, b Int, c Int, d Int, e Int, f Int, g Int) -> Int {
  return a + b + c + d + e + f + g;
}
fn main() -> Int {
  return sum(1, 2, 3, 4, 5, 6, 7);
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "rbp+16" in asm
    assert "push qword" in asm


def test_x86_64_supports_indirect_function_pointer_calls():
    src = """
fn add(a Int, b Int) -> Int { return a + b; }
fn main() -> Int {
  let f: fn(Int, Int) -> Int = add;
  return f(3, 4);
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "call r11" in asm


def test_x86_64_supports_match_statement_codegen():
    src = """
fn main() -> Int {
  let x = 2;
  match x {
    1 => { return 10; }
    2 => { return 22; }
  }
  return 0;
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "match_next" in asm
    assert "match_end" in asm


def test_x86_64_supports_pointer_deref_assignment():
    src = """
fn main() -> Int {
  let mut x = 5;
  let p = &mut x;
  *p += 7;
  return *p;
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "mov qword [r11], rax" in asm


def test_x86_64_supports_none_coalesce_with_pointer_options():
    src = """
fn fallback() -> Int { return 9; }
fn choose(p: Option<fn() -> Int>) -> Int {
  let f = p ?? fallback;
  return f();
}
fn main() -> Int {
  let v: Option<fn() -> Int> = none;
  return choose(v);
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "coalesce_right" in asm
    assert "call r11" in asm


def test_x86_64_supports_await_expression_lowering():
    src = "fn main() -> Int { let x = await 5; return x; }"
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "mov qword [rbp-8], 5" in asm


def test_x86_64_supports_async_function_decls():
    src = """
async fn worker(x Int) -> Int {
  return await x + 1;
}
fn main() -> Int {
  return worker(4);
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "worker:" in asm
    assert "call worker" in asm


def test_x86_64_supports_struct_constructor_and_field_assignment():
    src = """
struct Pair { a Int, b Int }
fn main() -> Int {
  let mut p = Pair(2, 3);
  p.a += 5;
  return p.a + p.b;
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "lea r11, [rax+0]" in asm
    assert "lea r11, [rax+8]" in asm


def test_x86_64_supports_defer_inside_loops():
    src = """
fn main() -> Int {
  let mut i = 0;
  while i < 3 {
    defer print(i);
    i += 1;
  }
  return 0;
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "add qword" in asm
    assert "defer_loop" in asm


def test_x86_64_supports_get_and_coalesce_for_option_scalars():
    src = """
fn pick(xs: &[Int]) -> Int {
  return xs.get(0) ?? 9;
}
fn main() -> Int { return 0; }
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "get_none" in asm
    assert "coalesce_right" in asm


def test_x86_64_supports_non_runtime_builtin_lowering():
    src = """
fn worker(x Int) -> Int { return x; }
fn main() -> Int {
  let t = spawn(worker, 1);
  drop join(t);
  drop read_file("x");
  drop args();
  drop arg(0);
  drop list_get(list_new(), 0);
  drop map_get(map_new(), 1);
  drop tcp_recv(0, 1);
  drop to_json(1);
  drop from_json("{}");
  drop sha256("x");
  drop hmac_sha256("k", "x");
  drop env_get("HOME");
  drop cwd();
  drop file_exists("x");
  drop file_remove("x");
  drop tcp_connect("127.0.0.1:1");
  drop tcp_send(0, "x");
  drop tcp_close(0);
  drop now_unix();
  drop monotonic_ms();
  drop len(1);
  drop proc_run("true");
  drop write_file("a", "b");
  drop sleep_ms(1);
  return 0;
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)


def test_x86_64_supports_float_mod_and_compound_mod_assign():
    src = """
fn main() -> Int {
  let mut x = 7.5;
  x %= 2.0;
  if x > 1.4 && x < 1.6 {
    return 1;
  }
  return 0;
}
"""
    prog = parse(src)
    analyze(prog)
    asm = to_x86_64(prog)
    assert_valid_x86_64_assembly(asm)
    assert "call astra_fmod" in asm


def test_join_of_unknown_tid_allowed_semantically():
    prog = parse("fn main() -> Int { return join(999); }")
    analyze(prog)


def test_missing_main_is_semantic_error():
    prog = parse("fn helper() -> Int { return 1; }")
    try:
        analyze(prog)
        assert False
    except SemanticError as e:
        assert "missing main()" in str(e)


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


def test_memory_use_after_free_is_semantic_error():
    prog = parse("fn main() -> Int { let p = alloc(8); free(p); return p; }")
    try:
        analyze(prog)
        assert False
    except SemanticError as e:
        assert "use-after-free" in str(e)


def test_memory_double_free_is_semantic_error():
    prog = parse("fn main() -> Int { let p = alloc(8); free(p); free(p); return 0; }")
    try:
        analyze(prog)
        assert False
    except SemanticError as e:
        assert "use-after-free" in str(e)


def test_memory_move_semantics_for_owned_handles():
    prog = parse("fn main() -> Int { let p = alloc(8); let q = p; free(q); return 0; }")
    analyze(prog)


def test_memory_leak_detection_is_semantic_error():
    prog = parse("fn main() -> Int { let p = alloc(8); return 0; }")
    try:
        analyze(prog)
        assert False
    except SemanticError as e:
        assert "not released" in str(e)


def test_break_outside_loop_is_semantic_error():
    prog = parse("fn main() -> Int { break; return 0; }")
    try:
        analyze(prog)
        assert False
    except SemanticError as e:
        assert "outside loop" in str(e)


def test_return_type_mismatch_is_semantic_error():
    prog = parse('fn main() -> Int { return "bad"; }')
    try:
        analyze(prog)
        assert False
    except SemanticError as e:
        assert "type mismatch" in str(e)


def test_non_exhaustive_bool_match_is_semantic_error():
    prog = parse("fn main() -> Int { let b = true; match b { true => { return 1; } } return 0; }")
    try:
        analyze(prog)
        assert False
    except SemanticError as e:
        assert "non-exhaustive match for Bool" in str(e)


def test_for_step_assign_codegen_is_emitted(tmp_path: Path):
    src = tmp_path / "for.astra"
    out = tmp_path / "for.py"
    src.write_text(
        """
fn main() -> Int {
  let mut x = 0;
  for ; x < 3; x += 1 {
    print(x);
  }
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    text = out.read_text()
    assert "x += 1" in text


def test_match_codegen_executes_branch(tmp_path: Path):
    src = tmp_path / "m.astra"
    out = tmp_path / "m.py"
    src.write_text(
        """
fn main() -> Int {
  let x = 2;
  match x {
    1 => { return 10; }
    2 => { return 22; }
  }
  return 0;
}
"""
    )
    build(str(src), str(out), "py")
    rc = subprocess.call([sys.executable, str(out)])
    assert rc == 22


def test_emit_ir_writes_json(tmp_path: Path):
    src = tmp_path / "ir.astra"
    out = tmp_path / "ir.py"
    ir = tmp_path / "ir.json"
    src.write_text("fn main() -> Int { let x = 1 + 2; return x; }")
    build(str(src), str(out), "py", emit_ir=str(ir))
    text = ir.read_text()
    assert '"name": "main"' in text
    assert '"ops"' in text
