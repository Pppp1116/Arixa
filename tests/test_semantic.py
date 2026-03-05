from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


def test_string_import_resolves_relative_module_file(tmp_path):
    dep = tmp_path / "dep.astra"
    dep.write_text("fn helper() -> Int { return 1; }")
    src = tmp_path / "main.astra"
    src.write_text('import "dep"; fn main() -> Int { return 0; }')
    analyze(parse(src.read_text(), filename=str(src)), filename=str(src))


def test_module_import_resolves_from_package_root(tmp_path):
    (tmp_path / "Astra.toml").write_text('name = "app"\n')
    (tmp_path / "lib").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "lib" / "util.astra").write_text("fn helper() -> Int { return 1; }")
    src = tmp_path / "src" / "main.astra"
    src.write_text("import lib.util; fn main() -> Int { return 0; }")
    analyze(parse(src.read_text(), filename=str(src)), filename=str(src))


def test_struct_constructor_and_field_types_ok():
    src = """
struct Point { x Int, y Int }
fn main() -> Int {
  let p = Point(1, 2);
  return 0;
}
"""
    analyze(parse(src))


def test_struct_constructor_arity_error():
    src = """
struct Point { x Int, y Int }
fn main() -> Int {
  let p = Point(1);
  return 0;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "expects 2 fields" in str(e)


def test_continue_outside_loop_error():
    src = "fn main() -> Int { continue; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "outside loop" in str(e)


def test_for_condition_must_be_bool():
    src = "fn main() -> Int { for ; 1; { return 0; } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "for condition" in str(e)


def test_for_in_requires_range_syntax():
    src = "fn main() -> Int { let xs = [1, 2, 3]; for x in xs { return x; } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except ParseError as e:
        assert "for-in currently supports only range syntax" in str(e)


def test_range_for_loop_typechecks():
    src = """
fn main() -> Int {
  let mut total = 0;
  for i in 1..=4 {
    total += i;
  }
  return total;
}
"""
    analyze(parse(src))


def test_missing_import_is_semantic_error():
    src = "import nope::missing; fn main() -> Int { return 0; }"
    try:
        analyze(parse(src), filename="tmp/input.astra")
        assert False
    except SemanticError as e:
        assert "cannot resolve import" in str(e)


def test_freestanding_allows_no_main():
    src = "fn kernel() -> Int { return 0; }"
    analyze(parse(src), freestanding=True)


def test_freestanding_rejects_hosted_runtime_builtin_calls():
    src = 'fn _start() -> Int { print("x"); return 0; }'
    try:
        analyze(parse(src), freestanding=True)
        assert False
    except SemanticError as e:
        assert "freestanding mode forbids builtin print" in str(e)


def test_freestanding_allows_pure_intrinsic_builtins():
    src = "fn _start() -> Int { return countOnes(7u4); }"
    analyze(parse(src), freestanding=True)


def test_coalesce_type_inference():
    src = "fn main() -> Int { let x: Option<Int> = none; let y: Int = x ?? 4; return y; }"
    analyze(parse(src))


def test_none_requires_option_context():
    src = "fn main() -> Int { let x = none; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "requires explicit Option<T>" in str(e)


def test_none_allowed_with_explicit_option_type():
    src = "fn main() -> Int { let x: Option<Int> = none; return x ?? 9; }"
    analyze(parse(src))


def test_option_type_accepts_plain_inner_value_as_some():
    src = "fn main() -> Int { let x: Option<Int> = 7; return x ?? 0; }"
    analyze(parse(src))


def test_coalesce_requires_option_left_operand():
    src = "fn main() -> Int { let x = 2 ?? 4; return x; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "left operand of ?? must be Option<T>" in str(e)


def test_type_sugar_question_mark_desugars_to_option():
    src = "fn main() -> Int { let x: Int? = none; return x ?? 1; }"
    analyze(parse(src))


def test_expression_statement_allows_discarding_non_void_values():
    src = "fn id(x Int) -> Int { return x; } fn main() -> Int { id(1); return 0; }"
    analyze(parse(src))


def test_drop_statement_allows_discarding_values():
    src = "fn id(x Int) -> Int { return x; } fn main() -> Int { drop id(1); return 0; }"
    analyze(parse(src))


def test_return_without_value_is_valid_for_void():
    src = "fn main() -> Void { return; }"
    analyze(parse(src))


def test_return_without_value_errors_for_non_void():
    src = "fn main() -> Int { return; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "type mismatch for return" in str(e)


def test_never_is_coercible_to_any_return_type():
    src = "fn die(code Int) -> Never { return proc_exit(code); } fn main() -> Int { return die(1); }"
    analyze(parse(src))


def test_never_expression_statement_is_valid():
    src = "fn main() -> Int { proc_exit(1); return 0; }"
    analyze(parse(src))


def test_defer_is_semantically_valid():
    src = 'fn main() -> Int { defer print("bye"); return 0; }'
    analyze(parse(src))


def test_match_wildcard_makes_bool_match_exhaustive():
    src = "fn main() -> Int { let b = true; match b { true => { return 1; }, _ => { return 0; } } return 0; }"
    analyze(parse(src))


def test_match_wildcard_must_be_last():
    src = "fn main() -> Int { let b = true; match b { _ => { return 1; }, false => { return 0; } } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "wildcard match arm must be last" in str(e)


def test_match_duplicate_bool_pattern_is_rejected():
    src = "fn main() -> Int { let b = true; match b { true => { return 1; }, true => { return 2; }, false => { return 3; } } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "duplicate Bool match arm for true" in str(e)


def test_specialization_prefers_concrete_impl():
    src = """
impl fn sum(x T) -> T { return x; }
impl fn sum(x Int) -> Int { return x + 1; }
fn main() -> Int { return sum(1); }
"""
    prog = parse(src)
    analyze(prog)
    call = prog.items[2].body[0].expr
    assert getattr(call, "resolved_name", "").startswith("sum__impl")


def test_specialization_ambiguous_impls_error():
    src = """
impl fn pick(x T) -> T { return x; }
impl fn pick(y U) -> U { return y; }
fn main() -> Int { return pick(1); }
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "ambiguous impl" in str(e) or "overlapping impl specializations" in str(e)


def test_specialization_respects_where_copy_constraint():
    src = """
impl fn dup<T>(x T) -> T where T: Copy { return x; }
fn main() -> Int { return dup(3); }
"""
    analyze(parse(src))


def test_specialization_rejects_where_copy_for_non_copy_type():
    src = """
struct Box { v Int }
impl fn dup<T>(x T) -> T where T: Copy { return x; }
fn main() -> Int { let b = Box(1); let _x = dup(b); return 0; }
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "no matching impl for dup(Box)" in str(e)


def test_overlapping_impls_with_same_specificity_rejected_early():
    src = """
impl fn choose<T>(x T) -> T { return x; }
impl fn choose<U>(y U) -> U { return y; }
fn main() -> Int { return 0; }
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "overlapping impl specializations" in str(e)


def test_function_references_infer_function_pointer_type():
    src = """
fn add(a Int, b Int) -> Int { return a + b; }
fn main() -> Int {
  let f = add;
  return f(3, 4);
}
"""
    prog = parse(src)
    analyze(prog)
    call = prog.items[1].body[1].expr
    assert getattr(call.fn, "inferred_type", "").startswith("fn(")


def test_str_type_accepts_string_literals():
    src = 'fn main() -> Int { let s: &str = "ok"; return 0; }'
    analyze(parse(src))


def test_slice_indexing_returns_element_type():
    src = "fn first(xs: &[u16]) -> u16 { return xs[0]; } fn main() -> Int { return 0; }"
    analyze(parse(src))


def test_vec_indexing_returns_element_type():
    src = "fn first(xs: Vec<i16>) -> i16 { return xs[0]; } fn main() -> Int { return 0; }"
    analyze(parse(src))


def test_vec_builtins_typecheck():
    src = """
fn main() -> Int {
  let mut v: Vec<Int> = vec_new() as Vec<Int>;
  drop vec_push(v, 1);
  drop vec_push(v, 2);
  drop vec_set(v, 1, 9);
  let got: Option<Int> = vec_get(v, 1);
  return vec_len(v) + (got ?? 0);
}
"""
    analyze(parse(src))


def test_vec_from_slice_infers_element_type():
    src = "fn main() -> Int { let mut v = vec_from([1, 2, 3]); drop vec_push(v, 4); return vec_len(v); }"
    analyze(parse(src))


def test_vec_builtins_reject_element_type_mismatch():
    src = """
fn main() -> Int {
  let mut v: Vec<Int> = vec_new() as Vec<Int>;
  drop vec_push(v, "x");
  return 0;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "arg 1 for vec_push" in str(e)


def test_bytes_alias_matches_vec_u8_in_calls():
    src = "fn first(xs: Vec<u8>) -> u8 { return xs[0]; } fn use_bytes(b: Bytes) -> u8 { return first(b); } fn main() -> Int { return 0; }"
    analyze(parse(src))


def test_string_indexing_is_rejected():
    src = 'fn main() -> Int { let s: String = "abc"; return s[0]; }'
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot index UTF-8 text directly" in str(e)


def test_string_concatenation_accepts_literals_and_strings():
    src = 'fn main() -> Int { let s = "a" + "b"; let t: String = s + "c"; return len(t); }'
    analyze(parse(src))


def test_str_indexing_is_rejected():
    src = 'fn first(s: &str) -> Int { return s[0]; } fn main() -> Int { return 0; }'
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot index UTF-8 text directly" in str(e)


def test_unsized_slice_param_by_value_is_rejected():
    src = "fn bad(xs: [Int]) -> Int { return 0; } fn main() -> Int { return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "unsized type [Int]" in str(e)


def test_unsized_str_local_by_value_is_rejected():
    src = 'fn main() -> Int { let s: str = "ok"; return 0; }'
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "unsized type str" in str(e)


def test_mixed_int_float_arithmetic_requires_explicit_cast():
    src = "fn main() -> Int { let x = 1 + 2.0; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "requires explicit cast" in str(e)


def test_cast_bool_to_int_is_allowed():
    src = "fn main() -> Int { let b = true; return b as Int; }"
    analyze(parse(src))


def test_strict_integer_binary_requires_matching_types():
    src = "fn main() -> Int { let a: u8 = 1 as u8; let b: u16 = 2 as u16; let x = a + b; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "matching integer types" in str(e)


def test_dynamic_integer_width_types_semantic_ok():
    src = """
fn main() -> Int {
  let a: u4 = 15u4;
  let b: u4 = 1u4;
  let c: u4 = a + b;
  return c as Int;
}
"""
    analyze(parse(src))


def test_dynamic_integer_width_requires_explicit_cast_for_mixed_widths():
    src = "fn main() -> Int { let a: u4 = 1u4; let b: u8 = 2 as u8; let c = a + b; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "matching integer types" in str(e)


def test_dynamic_integer_width_assignment_requires_explicit_cast():
    src = "fn main() -> Int { let x: u8 = 1u4; return x as Int; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot implicitly convert u4 to u8, use explicit cast" in str(e)


def test_semantic_supports_bit_intrinsics_for_integer_types():
    src = """
fn main() -> Int {
  let a = bitSizeOf(u3);
  let b: u4 = maxVal(u4);
  let c: i4 = minVal(i4);
  return a + (b as Int) + (c as Int);
}
"""
    analyze(parse(src))


def test_semantic_supports_bit_intrinsics_for_arbitrary_integer_widths():
    src = """
fn main() -> Int {
  let x: u4 = 3u4;
  let a = countOnes(x);
  let b = leadingZeros(x);
  let c = trailingZeros(x);
  return a + b + c;
}
"""
    analyze(parse(src))


def test_semantic_supports_popcnt_clz_ctz_aliases_and_rotates():
    src = """
fn main() -> Int {
  let x: u8 = 0b1001_0001u8;
  let a = popcnt(x);
  let b = clz(x);
  let c = ctz(x);
  let d: u8 = rotl(x, 1u8);
  let e: u8 = rotr(d, 1u8);
  return a + b + c + (e as Int);
}
"""
    analyze(parse(src))


def test_semantic_rejects_static_shift_count_out_of_range():
    src = "fn main() -> Int { let x: u8 = 1 as u8; return (x << (8 as u8)) as Int; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "shift count 8 out of range for u8 in <<" in str(e)


def test_semantic_rejects_static_negative_shift_count():
    src = "fn main() -> Int { let x: Int = 1; return x >> -1; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "shift count -1 out of range for Int in >>" in str(e)


def test_semantic_rejects_bit_intrinsics_on_non_integer_type():
    src = "fn main() -> Int { return countOnes(1.5); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "expects an integer argument" in str(e)


def test_semantic_rejects_rotates_on_non_integer_types():
    src = "fn main() -> Int { return rotl(1.5, 1) as Int; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "expects integer arg 0" in str(e)


def test_semantic_rejects_maxval_on_non_integer_type():
    src = "fn main() -> Int { let x = maxVal(Float); return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "maxVal expects an integer type" in str(e)


def test_semantic_rejects_signed_i1_with_hint():
    src = "fn main() -> Int { let x: i1 = 0 as i1; return x as Int; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "did you mean u1" in str(e)


def test_semantic_restricts_packed_struct_fields_to_integer_or_bool():
    src = """
@packed struct Bad {
  x: Float,
}
fn main() -> Int { return 0; }
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "packed struct fields must be integer or bool types" in str(e)


def test_semantic_accepts_packed_fields_above_64_bits():
    src = """
@packed struct BigPacked {
  a: u65,
  b: i127,
  c: u128,
}
fn main() -> Int { return 0; }
"""
    analyze(parse(src))


def test_call_of_non_function_reports_explicit_type_error():
    src = "fn main() -> Int { return (1)(); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot call value of non-function type Int" in str(e)


def test_layout_query_semantics_for_type_and_value_forms():
    src = "struct P { a Int, b u8 } fn main() -> Int { let p = P(1, 2 as u8); return sizeof(P) + alignof(P) + size_of(p.a) + align_of(p.b); }"
    analyze(parse(src))


def test_layout_query_rejects_opaque_and_unsized_types():
    src = "fn main() -> Int { return sizeof(String); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "not queryable" in str(e)


def test_mutable_borrow_blocks_shared_borrow():
    src = "fn main() -> Int { let mut x = 1; let r = &mut x; let s = &x; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot immutably borrow x while it is mutably borrowed" in str(e)


def test_shared_borrow_blocks_mutation():
    src = "fn main() -> Int { let mut x = 1; let r = &x; x = 2; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot mutate x while it is immutably borrowed" in str(e)


def test_mutable_borrow_blocks_direct_use_of_owner():
    src = "fn main() -> Int { let mut x = 1; let r = &mut x; return x; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot use x while it is mutably borrowed" in str(e)


def test_multiple_shared_borrows_are_allowed():
    src = "fn main() -> Int { let mut x = 1; let a = &x; let b = &x; return *a + *b; }"
    analyze(parse(src))


def test_mutable_borrow_requires_mutable_binding():
    src = "fn main() -> Int { fixed x = 1; let r = &mut x; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot mutably borrow fixed binding x" in str(e)


def test_ref_return_without_ref_param_is_rejected():
    src = "fn bad() -> &Int { let x = 1; return &x; } fn main() -> Int { return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "returns a reference but has no reference parameter" in str(e)


def test_ref_return_must_tie_to_ref_param():
    src = "fn f(xs: &[Int]) -> &Int { let x = 1; let r = &x; return r; } fn main() -> Int { return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "returned reference is not tied to an input reference parameter" in str(e)


def test_ref_return_alias_of_ref_param_is_allowed():
    src = "fn f(xs: &Int) -> &Int { let y = xs; return y; } fn main() -> Int { return 0; }"
    analyze(parse(src))


def test_use_after_move_is_rejected_for_non_copy_values():
    src = "struct S { v Int } fn main() -> Int { let a = S(1); let b = a; return a.v; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "use-after-move of a" in str(e)


def test_drop_consumes_non_copy_values():
    src = "struct S { v Int } fn main() -> Int { let a = S(1); drop a; return a.v; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "use-after-move of a" in str(e)


def test_drop_releases_alloc_owned_handle():
    src = "fn main() -> Int { let p = alloc(8); drop p; return 0; }"
    analyze(parse(src))


def test_copy_values_are_usable_after_assignment():
    src = "fn main() -> Int { let a = 7; let b = a; return a + b; }"
    analyze(parse(src))


def test_slice_get_returns_option_type():
    src = "fn main() -> Int { let x: Option<Int> = [1, 2].get(0); return x ?? 0; }"
    analyze(parse(src))


def test_struct_callable_field_named_get_is_not_treated_as_slice_sugar():
    src = """
struct Wrap { get fn(Int) -> Int }
fn add1(x Int) -> Int { return x + 1; }
fn main() -> Int {
  let w = Wrap(add1);
  return w.get(41);
}
"""
    analyze(parse(src))


def test_owned_internal_use_after_free_reports_exact_location():
    filename = "tmp/owned_use_after_free.astra"
    src = (
        "fn main() -> Int {\n"
        "  let p = alloc(8);\n"
        "  free(p);\n"
        "  free(p);\n"
        "  return 0;\n"
        "}\n"
    )
    try:
        analyze(parse(src, filename=filename), filename=filename)
        assert False
    except SemanticError as e:
        assert str(e) == "SEM tmp/owned_use_after_free.astra:4:8: use-after-free of p"


def test_owned_internal_use_after_move_reports_exact_location():
    filename = "tmp/owned_use_after_move.astra"
    src = (
        "fn main() -> Int {\n"
        "  let p = alloc(8);\n"
        "  let q = p;\n"
        "  let r = p;\n"
        "  return 0;\n"
        "}\n"
    )
    try:
        analyze(parse(src, filename=filename), filename=filename)
        assert False
    except SemanticError as e:
        assert str(e) == "SEM tmp/owned_use_after_move.astra:4:11: use-after-move of p"


def test_owned_internal_reassignment_leak_reports_exact_location():
    filename = "tmp/owned_reassign_leak.astra"
    src = (
        "fn main() -> Int {\n"
        "  let p = alloc(8);\n"
        "  p = alloc(16);\n"
        "  return 0;\n"
        "}\n"
    )
    try:
        analyze(parse(src, filename=filename), filename=filename)
        assert False
    except SemanticError as e:
        assert str(e) == (
            "SEM tmp/owned_reassign_leak.astra:3:3: "
            "reassignment would leak owned allocation in p; free or move it first"
        )


def test_any_to_concrete_requires_explicit_cast():
    src = "fn main() -> Int { return join(1); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "type mismatch for return" in str(e)


def test_any_explicit_downcast_is_allowed():
    src = "fn worker(x Int) -> Int { return x; } fn main() -> Int { let t = spawn(worker, 1); return join(t) as Int; }"
    analyze(parse(src))


def test_calling_unsafe_fn_requires_unsafe_context():
    src = "unsafe fn danger() -> Int { return 1; } fn main() -> Int { return danger(); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "requires unsafe context" in str(e)


def test_unsafe_block_allows_calling_unsafe_fn():
    src = "unsafe fn danger() -> Int { return 1; } fn main() -> Int { unsafe { return danger(); } }"
    analyze(parse(src))


def test_unsafe_fn_allows_calling_unsafe_fn():
    src = "unsafe fn danger() -> Int { return 1; } unsafe fn main() -> Int { return danger(); }"
    analyze(parse(src))


def test_spawn_rejects_non_send_argument_types():
    src = """
fn worker(x Any) -> Int { return 0; }
fn main() -> Int {
  let x = from_json("1");
  let t = spawn(worker, x);
  return join(t) as Int;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "spawn arg 1 requires Send" in str(e)


def test_spawn_rejects_shared_refs_to_non_sync_types():
    src = """
fn worker(v &Vec<Int>) -> Int { return vec_len(*v); }
fn main() -> Int {
  let v: Vec<Int> = vec_new() as Vec<Int>;
  let t = spawn(worker, &v);
  return join(t) as Int;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "spawn arg 1 requires Send" in str(e)


def test_duplicate_type_definitions_are_rejected():
    src = "enum R { A } enum R { B } fn main() -> Int { return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "duplicate type definition R" in str(e)


def test_any_binding_named_like_type_does_not_infer_struct_fields():
    src = "struct Box { v Int } fn main() -> Int { let Box: Any = 1; let y = Box.v; return y as Int; }"
    prog = parse(src)
    analyze(prog)
    expr = prog.items[1].body[1].expr
    assert getattr(expr, "inferred_type", None) == "Any"


def test_enum_match_exhaustive_with_variant_patterns_and_bindings():
    src = """
enum Result { Ok(Int), Err(Int) }
fn main() -> Int {
  let v = Result.Ok(7);
  match v {
    Result.Ok(x) => { return x; },
    Result.Err(_) => { return 0; }
  }
}
"""
    analyze(parse(src))


def test_enum_match_reports_non_exhaustive_variants():
    src = """
enum Result { Ok(Int), Err(Int) }
fn main() -> Int {
  let v = Result.Ok(7);
  match v {
    Result.Ok(_) => { return 1; }
  }
  return 0;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "non-exhaustive match for Result" in str(e)


def test_enum_match_duplicate_variant_arm_is_rejected():
    src = """
enum Result { Ok(Int), Err(Int) }
fn main() -> Int {
  let v = Result.Ok(7);
  match v {
    Result.Ok(_) => { return 1; },
    Result.Ok(_) => { return 2; },
    Result.Err(_) => { return 0; }
  }
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "unreachable duplicate enum match arm" in str(e)
