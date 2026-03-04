import subprocess
import sys
from pathlib import Path

from astra.ast import Binary, FieldExpr, FnDecl, LetStmt, Literal, Name, Program, ReturnStmt, StructDecl, StructLit, TypeAnnotated
from astra.asm_assert import assert_valid_llvm_ir
from astra.build import build
from astra.codegen import to_python
from astra.llvm_codegen import to_llvm_ir
from astra.parser import parse
from astra.semantic import SemanticError, analyze


def test_spawn_builtin_semantic_ok():
    prog = parse("fn worker(x Int) -> Int { return x; } fn main() -> Int { let t = spawn(worker, 1); return join(t) as Int; }")
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


def _manual_struct_literal_program() -> Program:
    pair = StructDecl(name="Pair", generics=[], fields=[("x", "Int"), ("y", "Int")], methods=[])
    p_lit = StructLit(name="Pair", fields=[("x", Literal(4)), ("y", Literal(6))])
    ret = ReturnStmt(Binary("+", FieldExpr(Name("p"), "x"), TypeAnnotated(FieldExpr(Name("p"), "y"), "Int")))
    main = FnDecl(name="main", generics=[], params=[], ret="Int", body=[LetStmt("p", p_lit), ret])
    return Program(items=[pair, main])


def test_struct_literal_and_type_annotation_semantics_are_supported():
    prog = _manual_struct_literal_program()
    analyze(prog)


def test_python_codegen_supports_struct_literal_and_type_annotation():
    prog = _manual_struct_literal_program()
    py = to_python(prog, freestanding=True)
    ns = {"__name__": "not_main"}
    exec(py, ns)
    assert ns["main"]() == 10


def test_llvm_codegen_supports_struct_literal_and_type_annotation():
    prog = _manual_struct_literal_program()
    mod = to_llvm_ir(prog)
    assert_valid_llvm_ir(mod)
    assert "define i32 @main()" in mod


def test_python_codegen_emits_width_aware_bit_intrinsic_calls():
    py = to_python(parse("fn main() -> Int { return countOnes(3u4) + leadingZeros(3u4) + trailingZeros(3u4); }"))
    assert "countOnes(__astra_cast(3, 'u4'), 4)" in py
    assert "leadingZeros(__astra_cast(3, 'u4'), 4)" in py
    assert "trailingZeros(__astra_cast(3, 'u4'), 4)" in py


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


def test_llvm_ir_has_runtime_entry_and_main():
    mod = to_llvm_ir(parse("fn main() -> Int { return 0; }"))
    assert_valid_llvm_ir(mod)
    assert "define i32 @main()" in mod
    assert "astra_run_py" not in mod


def test_llvm_ir_freestanding_has_start():
    mod = to_llvm_ir(parse("fn _start() -> Int { return 0; }"), freestanding=True)
    assert_valid_llvm_ir(mod)
    assert "define i64 @_start()" in mod


def test_llvm_build_writes_expected_ir(tmp_path: Path):
    src = tmp_path / "prog.astra"
    out = tmp_path / "prog.ll"
    src.write_text("fn main() -> Int { return 0; }")
    build(str(src), str(out), "llvm")
    mod = out.read_text()
    assert_valid_llvm_ir(mod, workdir=tmp_path)
    assert mod == to_llvm_ir(parse(src.read_text()))


def test_llvm_supports_overflow_mode_variants():
    src = """
fn main() -> Int {
  let a: i128 = 20 as i128;
  let b: i128 = 3 as i128;
  let m: i128 = a * b;
  let d: i128 = a / b;
  let r: i128 = a % b;
  return (m as Int) + (d as Int) + (r as Int);
}
"""
    prog = parse(src)
    analyze(prog)
    mod_trap = to_llvm_ir(prog, overflow_mode="trap")
    mod_wrap = to_llvm_ir(prog, overflow_mode="wrap")
    assert_valid_llvm_ir(mod_trap)
    assert_valid_llvm_ir(mod_wrap)


def test_llvm_packed_struct_fields_lower_with_bit_ops():
    src = """
@packed struct Header { a: u4, b: u3, c: u1, d: u8 }
fn main() -> Int {
  let mut h = Header(3u4, 5u3, 1u1, 9u8);
  h.a += 1u4;
  h.d = 7u8;
  return (h.a as Int) + (h.b as Int) + (h.c as Int) + (h.d as Int);
}
"""
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)
    # Packed field accesses should be lowered via bit slicing (shift/mask style ops).
    assert "lshr" in mod
    assert "shl" in mod
    assert "and" in mod
    assert "or" in mod


def test_llvm_packed_struct_fields_above_64_bits_lower_with_wide_windows():
    src = """
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
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)
    assert "i136" in mod
    assert "lshr" in mod
    assert "shl" in mod


def test_llvm_valid_surface_program_does_not_report_unsupported_diagnostics():
    src = """
fn add(x: Int, y: Int) -> Int { return x + y; }
fn main() -> Int {
  let mut a: u8 = 7 as u8;
  a += 2 as u8;
  let b = countOnes(a);
  let c = leadingZeros(a);
  let d = trailingZeros(a);
  let e = add(1, 2);
  if (a as Int) > 0 && e == 3 {
    return b + c + d + e;
  }
  return 0;
}
"""
    try:
        mod = to_llvm_ir(parse(src))
    except Exception as e:
        assert "unsupported" not in str(e)
        raise
    assert_valid_llvm_ir(mod)


def test_llvm_shift_ops_emit_runtime_range_guards():
    src = """
fn main() -> Int {
  let x: u8 = 1 as u8;
  let s: u8 = 8 as u8;
  return (x << s) as Int;
}
"""
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)
    assert "llvm.trap" in mod
    assert "shift_oob" in mod


def test_llvm_int_divrem_emit_runtime_guards():
    src = """
fn divmod(a: Int, b: Int) -> Int {
  return (a / b) + (a % b);
}
fn main() -> Int { return divmod(11, 3); }
"""
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)
    assert "sdiv" in mod
    assert "srem" in mod
    assert "divrem_bad" in mod
    assert "llvm.trap" in mod


def test_llvm_float_to_int_casts_use_saturating_intrinsics():
    src = """
fn main() -> Int {
  let x: Float = 1.5;
  let y: u8 = x as u8;
  return (x as Int) + (y as Int);
}
"""
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)
    assert "llvm.fptosi.sat.i64.f64" in mod
    assert "llvm.fptoui.sat.i8.f64" in mod
    assert "fptosi " not in mod
    assert "fptoui " not in mod


def test_llvm_lowering_covers_extended_runtime_builtins():
    src = """
fn worker(x: Int) -> Int { return x + 1; }
fn main() -> Int {
  let t = spawn(worker, 1);
  drop join(t);
  drop await_result(1);
  drop args();
  drop arg(0);
  let xs = list_new();
  drop list_push(xs, 1);
  drop list_set(xs, 0, 2);
  drop list_get(xs, 0);
  drop list_len(xs);
  let m = map_new();
  drop map_set(m, 1, 2);
  drop map_has(m, 1);
  drop map_get(m, 1);
  drop read_file("missing.txt");
  drop write_file("tmp.txt", "x");
  drop file_exists("tmp.txt");
  drop file_remove("tmp.txt");
  drop tcp_connect("127.0.0.1:1");
  drop tcp_send(0, "x");
  drop tcp_recv(0, 8);
  drop tcp_close(0);
  drop to_json(1);
  drop from_json("1");
  drop sha256("abc");
  drop hmac_sha256("k", "v");
  drop env_get("HOME");
  drop cwd();
  drop proc_run("true");
  drop now_unix();
  drop monotonic_ms();
  drop sleep_ms(1);
  return 0;
}
"""
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)
    for sym in (
        "astra_spawn_store",
        "astra_join",
        "astra_args",
        "astra_arg",
        "astra_list_new",
        "astra_map_new",
        "astra_read_file",
        "astra_write_file",
        "astra_file_exists",
        "astra_tcp_connect",
        "astra_to_json",
        "astra_sha256",
        "astra_env_get",
        "astra_cwd",
        "astra_proc_run",
        "astra_now_unix",
        "astra_sleep_ms",
    ):
        assert sym in mod


def test_llvm_cross_target_emission():
    src = parse("fn main() -> Int { return 0; }")
    for triple in (
        "x86_64-unknown-linux-gnu",
        "aarch64-unknown-linux-gnu",
        "riscv64-unknown-linux-gnu",
        "wasm32-unknown-unknown",
    ):
        mod = to_llvm_ir(src, triple=triple)
        assert_valid_llvm_ir(mod, triple=triple)


def test_join_of_unknown_tid_allowed_semantically():
    prog = parse("fn main() -> Int { return join(999) as Int; }")
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
    src = "fn worker(x Int) -> Int { return x; } fn main() -> Int { let t = spawn(worker, 3); return join(t) as Int; }"
    py = to_python(parse(src))
    assert "spawn(worker, 3)" in py
    assert "join(t)" in py


def test_llvm_any_casts_use_runtime_box_unbox_helpers():
    src = """
fn main() -> Int {
  let x: Any = 7;
  let y: Int = x as Int;
  let s: Any = "ok";
  let s2: String = s as String;
  drop len(s2);
  drop to_json(s);
  return y;
}
"""
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)
    assert "astra_any_box_i64" in mod
    assert "astra_any_to_i64" in mod
    assert "astra_any_box_str" in mod


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


def test_emit_ir_writes_llvm_text(tmp_path: Path):
    src = tmp_path / "ir.astra"
    out = tmp_path / "ir.py"
    ir = tmp_path / "ir.ll"
    src.write_text("fn main() -> Int { let x = 1 + 2; return x; }")
    build(str(src), str(out), "py", emit_ir=str(ir))
    text = ir.read_text()
    assert "define i32 @main()" in text
    assert "astra_run_py" not in text


def test_runtime_c_exports_i128_helper_symbols():
    text = Path("runtime/llvm_runtime.c").read_text()
    for sym in (
        "astra_i128_mul_wrap",
        "astra_i128_mul_trap",
        "astra_u128_mul_wrap",
        "astra_u128_mul_trap",
        "astra_i128_div_wrap",
        "astra_i128_div_trap",
        "astra_u128_div_wrap",
        "astra_u128_div_trap",
        "astra_i128_mod_wrap",
        "astra_i128_mod_trap",
        "astra_u128_mod_wrap",
        "astra_u128_mod_trap",
    ):
        assert sym in text


def test_runtime_c_exports_extended_builtin_symbols():
    text = Path("runtime/llvm_runtime.c").read_text()
    for sym in (
        "astra_len_any",
        "astra_len_str",
        "astra_read_file",
        "astra_write_file",
        "astra_args",
        "astra_arg",
        "astra_spawn_store",
        "astra_join",
        "astra_list_new",
        "astra_list_push",
        "astra_map_new",
        "astra_map_has",
        "astra_file_exists",
        "astra_tcp_connect",
        "astra_to_json",
        "astra_from_json",
        "astra_sha256",
        "astra_hmac_sha256",
        "astra_env_get",
        "astra_cwd",
        "astra_proc_run",
        "astra_now_unix",
        "astra_monotonic_ms",
        "astra_sleep_ms",
    ):
        assert sym in text


def test_llvm_field_get_callable_struct_field_not_treated_as_slice_sugar():
    src = """
struct Wrap { get fn(Int) -> Int }
fn add1(x Int) -> Int { return x + 1; }
fn main() -> Int {
  let w = Wrap(add1);
  return w.get(41);
}
"""
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)


def test_llvm_supports_secure_bytes_and_utf8_builtins():
    src = """
fn main() -> Int {
  let b = secure_bytes(4);
  let sopt: Option<String> = utf8_decode(utf8_encode("ok"));
  let s = sopt ?? "";
  return vec_len(b) + len(s);
}
"""
    mod = to_llvm_ir(parse(src))
    assert_valid_llvm_ir(mod)
