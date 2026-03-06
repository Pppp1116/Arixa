from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


def test_string_import_resolves_relative_module_file(tmp_path):
    dep = tmp_path / "dep.astra"
    dep.write_text("fn helper() Int{ return 1; }")
    src = tmp_path / "main.astra"
    src.write_text('import "dep"; fn main() Int{ return 0; }')
    analyze(parse(src.read_text(), filename=str(src)), filename=str(src))


def test_module_import_resolves_from_package_root(tmp_path):
    (tmp_path / "Astra.toml").write_text('name = "app"\n')
    (tmp_path / "lib").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "lib" / "util.astra").write_text("fn helper() Int{ return 1; }")
    src = tmp_path / "src" / "main.astra"
    src.write_text("import lib.util; fn main() Int{ return 0; }")
    analyze(parse(src.read_text(), filename=str(src)), filename=str(src))


def test_struct_constructor_and_field_types_ok():
    src = """
struct Point { x Int, y Int }
fn main() Int{
  p = Point(1, 2);
  return 0;
}
"""
    analyze(parse(src))


def test_struct_constructor_arity_error():
    src = """
struct Point { x Int, y Int }
fn main() Int{
  p = Point(1);
  return 0;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "expects 2 fields" in str(e)


def test_continue_outside_loop_error():
    src = "fn main() Int{ continue; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "outside loop" in str(e)


def test_for_condition_must_be_bool():
    src = "fn main() Int{ for i = 0; i < 3; i += 1 { return 0; } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except ParseError as e:
        assert "for expects `for <ident> in <expr> { ... }`" in str(e)


def test_for_in_rejects_non_iterable_type():
    src = "fn main() Int{ for x in 7 { return x; } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "is not iterable" in str(e)


def test_range_for_loop_typechecks():
    src = """
fn main() Int{
  mut total = 0;
  for i in 1..=4 {
    total += i;
  }
  return total;
}
"""
    analyze(parse(src))


def test_vec_for_loop_typechecks():
    src = """
fn main() Int{
  mut v: Vec<Int> = vec_new() as Vec<Int>;
  drop vec_push(v, 2);
  drop vec_push(v, 3);
  mut acc = 0;
  for x in v { acc += x; }
  return acc;
}
"""
    analyze(parse(src))


def test_slice_for_loop_typechecks():
    src = """
fn main(xs &[Int]) Int{
  mut acc = 0;
  for x in xs { acc += x; }
  return acc;
}
"""
    analyze(parse(src))


def test_bytes_for_loop_typechecks():
    src = """
fn main() Int{
  b: Bytes = vec_from([1u8, 2u8, 3u8]);
  mut acc = 0;
  for x in b { acc += x as Int; }
  return acc;
}
"""
    analyze(parse(src))


def test_for_in_over_non_copy_elements_is_rejected():
    src = """
struct Boxed { x: Int }
fn main() Int{
  mut xs: Vec<Boxed> = vec_new() as Vec<Boxed>;
  drop vec_push(xs, Boxed(1));
  for v in xs { return v.x; }
  return 0;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "requires Copy element type" in str(e)


def test_missing_import_is_semantic_error():
    src = "import nope::missing; fn main() Int{ return 0; }"
    try:
        analyze(parse(src), filename="tmp/input.astra")
        assert False
    except SemanticError as e:
        assert "cannot resolve import" in str(e)


def test_freestanding_allows_no_main():
    src = "fn kernel() Int{ return 0; }"
    analyze(parse(src), freestanding=True)


def test_freestanding_rejects_hosted_runtime_builtin_calls():
    src = 'fn _start() Int{ print("x"); return 0; }'
    try:
        analyze(parse(src), freestanding=True)
        assert False
    except SemanticError as e:
        assert "freestanding mode forbids builtin print" in str(e)


def test_freestanding_allows_pure_intrinsic_builtins():
    src = "fn _start() Int{ return countOnes(7u4); }"
    analyze(parse(src), freestanding=True)


def test_coalesce_type_inference():
    src = "fn main() Int{ x: Option<Int> = none; y: Int = x ?? 4; return y; }"
    analyze(parse(src))


def test_none_requires_option_context():
    src = "fn main() Int{ x = none; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "requires explicit nullable type" in str(e)


def test_none_allowed_with_explicit_option_type():
    src = "fn main() Int{ x: Option<Int> = none; return x ?? 9; }"
    analyze(parse(src))


def test_option_type_accepts_plain_inner_value_as_some():
    src = "fn main() Int{ x: Option<Int> = 7; return x ?? 0; }"
    analyze(parse(src))


def test_coalesce_requires_option_left_operand():
    src = "fn main() Int{ x = 2 ?? 4; return x; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "left operand of ?? must be nullable" in str(e)


def test_type_sugar_question_mark_desugars_to_option():
    src = "fn main() Int{ x: Int? = none; return x ?? 1; }"
    analyze(parse(src))


def test_try_operator_typechecks_for_option_in_option_returning_fn():
    src = """
fn helper(v Option<Int>) Option<Int>{
  x = v!;
  return x;
}
fn main() Int{ return 0; }
"""
    analyze(parse(src))


def test_try_operator_requires_option_operand():
    src = "fn helper(v Int) Option<Int>{ return v!; } fn main() Int{ return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "`!` expects a fallible union operand" in str(e)


def test_try_operator_requires_option_return_type():
    src = "fn helper(v Option<Int>) Int{ return v!; } fn main() Int{ return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "`!` on Option<T> requires function return Option<U>" in str(e)


def test_try_operator_typechecks_for_result_in_result_returning_fn():
    src = """
enum Result<T, E> {
  Ok(T),
  Err(E),
}
fn parse(v Int) Result<Int, Int>{
  if v > 0 {
    return Result.Ok(v);
  }
  else {}
  return Result.Err(1);
}
fn helper(v Int) Result<Int, Int>{
  x = parse(v)!;
  return Result.Ok(x + 1);
}
fn main() Int{ return 0; }
"""
    analyze(parse(src))


def test_try_operator_result_requires_result_return_type():
    src = """
enum Result<T, E> {
  Ok(T),
  Err(E),
}
fn parse(v Int) Result<Int, Int>{
  if v > 0 { return Result.Ok(v); } else {}
  return Result.Err(1);
}
fn helper(v Int) Int{
  x = parse(v)!;
  return x;
}
fn main() Int{ return 0; }
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "`!` on Result<T, E> requires function return Result<U, E>" in str(e)


def test_try_operator_result_requires_matching_error_type():
    src = """
enum Result<T, E> {
  Ok(T),
  Err(E),
}
fn parse(v Int) Result<Int, Int>{
  if v > 0 { return Result.Ok(v); } else {}
  return Result.Err(1);
}
fn helper(v Int) Result<Int, String>{
  x = parse(v)!;
  return Result.Ok(x);
}
fn main() Int{ return 0; }
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "result error type" in str(e)


def test_expression_statement_allows_discarding_non_void_values():
    src = "fn id(x Int) Int{ return x; } fn main() Int{ id(1); return 0; }"
    analyze(parse(src))


def test_drop_statement_allows_discarding_values():
    src = "fn id(x Int) Int{ return x; } fn main() Int{ drop id(1); return 0; }"
    analyze(parse(src))


def test_return_without_value_is_valid_for_void():
    src = "fn main() Void{ return; }"
    analyze(parse(src))


def test_return_without_value_errors_for_non_void():
    src = "fn main() Int{ return; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "type mismatch for return" in str(e)


def test_never_is_coercible_to_any_return_type():
    src = "fn die(code Int) Never{ return proc_exit(code); } fn main() Int{ return die(1); }"
    analyze(parse(src))


def test_never_expression_statement_is_valid():
    src = "fn main() Int{ proc_exit(1); return 0; }"
    analyze(parse(src))


def test_defer_is_semantically_valid():
    src = 'fn main() Int{ defer print("bye"); return 0; }'
    analyze(parse(src))


def test_match_wildcard_makes_bool_match_exhaustive():
    src = "fn main() Int{ b = true; match b { true => { return 1; }, _ => { return 0; } } return 0; }"
    analyze(parse(src))


def test_match_wildcard_must_be_last():
    src = "fn main() Int{ b = true; match b { _ => { return 1; }, false => { return 0; } } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "wildcard match arm must be last" in str(e)


def test_match_duplicate_bool_pattern_is_rejected():
    src = "fn main() Int{ b = true; match b { true => { return 1; }, true => { return 2; }, false => { return 3; } } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "duplicate Bool match arm for true" in str(e)


def test_match_non_exhaustive_enum_is_rejected():
    src = """
enum Color {
  Red,
  Green,
  Blue,
}
fn main() Int{
  c: Color = Color.Red;
  match c {
    Color.Red => { return 1; }
    Color.Green => { return 2; }
  }
  return 0;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "non-exhaustive match for enum Color" in str(e)


def test_match_duplicate_enum_variant_is_rejected():
    src = """
enum Color {
  Red,
  Green,
}
fn main() Int{
  c: Color = Color.Red;
  match c {
    Color.Red => { return 1; }
    Color.Red => { return 2; }
    Color.Green => { return 3; }
  }
  return 0;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "duplicate enum match arm for Color.Red" in str(e)


def test_match_guarded_bool_arms_do_not_count_for_exhaustiveness():
    src = """
fn main() Int{
  b = true;
  match b {
    true if false => { return 1; }
    false => { return 0; }
  }
  return 0;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "non-exhaustive match for Bool" in str(e)


def test_match_or_pattern_bool_is_exhaustive():
    src = "fn main() Int{ b = true; match b { true | false => { return 1; } } return 0; }"
    analyze(parse(src))


def test_match_wildcard_cannot_be_combined_with_or_pattern():
    src = "fn main() Int{ b = true; match b { _ | true => { return 1; } false => { return 0; } } return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "wildcard pattern `_` cannot be combined with `|` alternatives" in str(e)


def test_specialization_prefers_concrete_impl():
    src = """
fn sum(x T) T{ return x; }
fn sum(x Int) Int{ return x + 1; }
fn main() Int{ return sum(1); }
"""
    prog = parse(src)
    analyze(prog)
    call = prog.items[2].body[0].expr
    assert getattr(call, "resolved_name", "").startswith("sum__impl")


def test_specialization_ambiguous_impls_error():
    src = """
fn pick(x T) T{ return x; }
fn pick(y U) U{ return y; }
fn main() Int{ return pick(1); }
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "ambiguous overload" in str(e)


def test_where_clause_trait_bound_allows_matching_impl():
    src = """
trait Show {
  fn show(x Self) String;
}
fn show(x Int) String { return "ok"; }
fn wrap(x T) T where T: Show{ return x; }
fn main() Int{ return wrap(9); }
"""
    analyze(parse(src))


def test_where_clause_trait_bound_rejects_non_impl_type():
    src = """
trait Show {
  fn show(x Self) String;
}
fn show(x Int) String { return "ok"; }
fn wrap(x T) T where T: Show{ return x; }
fn main() Int{ return wrap(1.5); }
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "no matching overload for wrap(Float)" in str(e)


def test_where_clause_rejects_unknown_trait():
    src = "fn wrap(x T) T where T: MissingTrait{ return x; } fn main() Int{ return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "unknown trait MissingTrait in where clause" in str(e)


def test_function_references_infer_function_pointer_type():
    src = """
fn add(a Int, b Int) Int{ return a + b; }
fn main() Int{
  f = add;
  return f(3, 4);
}
"""
    prog = parse(src)
    analyze(prog)
    call = prog.items[1].body[1].expr
    assert getattr(call.fn, "inferred_type", "").startswith("fn(")


def test_str_type_accepts_string_literals():
    src = 'fn main() Int{ s: &str = "ok"; return 0; }'
    analyze(parse(src))


def test_slice_indexing_returns_element_type():
    src = "fn first(xs &[u16]) u16{ return xs[0]; } fn main() Int{ return 0; }"
    analyze(parse(src))


def test_vec_indexing_returns_element_type():
    src = "fn first(xs Vec<i16>) i16{ return xs[0]; } fn main() Int{ return 0; }"
    analyze(parse(src))


def test_vec_builtins_typecheck():
    src = """
fn main() Int{
  mut v: Vec<Int> = vec_new() as Vec<Int>;
  drop vec_push(v, 1);
  drop vec_push(v, 2);
  drop vec_set(v, 1, 9);
  got: Option<Int> = vec_get(v, 1);
  return vec_len(v) + (got ?? 0);
}
"""
    analyze(parse(src))


def test_vec_from_slice_infers_element_type():
    src = "fn main() Int{ mut v = vec_from([1, 2, 3]); drop vec_push(v, 4); return vec_len(v); }"
    analyze(parse(src))


def test_vec_builtins_reject_element_type_mismatch():
    src = """
fn main() Int{
  mut v: Vec<Int> = vec_new() as Vec<Int>;
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
    src = "fn first(xs Vec<u8>) u8{ return xs[0]; } fn use_bytes(b Bytes) u8{ return first(b); } fn main() Int{ return 0; }"
    analyze(parse(src))


def test_string_indexing_is_rejected():
    src = 'fn main() Int{ s: String = "abc"; return s[0]; }'
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot index UTF-8 text directly" in str(e)


def test_string_concatenation_accepts_literals_and_strings():
    src = 'fn main() Int{ s = "a" + "b"; t: String = s + "c"; return len(t); }'
    analyze(parse(src))


def test_str_indexing_is_rejected():
    src = 'fn first(s &str) Int{ return s[0]; } fn main() Int{ return 0; }'
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot index UTF-8 text directly" in str(e)


def test_unsized_slice_param_by_value_is_rejected():
    src = "fn bad(xs [Int]) Int{ return 0; } fn main() Int{ return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "unsized type [Int]" in str(e)


def test_unsized_str_local_by_value_is_rejected():
    src = 'fn main() Int{ s: str = "ok"; return 0; }'
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "unsized type str" in str(e)


def test_mixed_int_float_arithmetic_requires_explicit_cast():
    src = "fn main() Int{ x = 1 + 2.0; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "requires explicit cast" in str(e)


def test_cast_bool_to_int_is_allowed():
    src = "fn main() Int{ b = true; return b as Int; }"
    analyze(parse(src))


def test_strict_integer_binary_requires_matching_types():
    src = "fn main() Int{ a: u8 = 1 as u8; b: u16 = 2 as u16; x = a + b; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "matching integer types" in str(e)


def test_dynamic_integer_width_types_semantic_ok():
    src = """
fn main() Int{
  a: u4 = 15u4;
  b: u4 = 1u4;
  c: u4 = a + b;
  return c as Int;
}
"""
    analyze(parse(src))


def test_dynamic_integer_width_requires_explicit_cast_for_mixed_widths():
    src = "fn main() Int{ a: u4 = 1u4; b: u8 = 2 as u8; c = a + b; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "matching integer types" in str(e)


def test_dynamic_integer_width_assignment_requires_explicit_cast():
    src = "fn main() Int{ x: u8 = 1u4; return x as Int; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot implicitly convert u4 to u8, use explicit cast" in str(e)


def test_semantic_supports_bit_intrinsics_for_integer_types():
    src = """
fn main() Int{
  a = bitSizeOf(u3);
  b: u4 = maxVal(u4);
  c: i4 = minVal(i4);
  return a + (b as Int) + (c as Int);
}
"""
    analyze(parse(src))


def test_semantic_supports_bit_intrinsics_for_arbitrary_integer_widths():
    src = """
fn main() Int{
  x: u4 = 3u4;
  a = countOnes(x);
  b = leadingZeros(x);
  c = trailingZeros(x);
  return a + b + c;
}
"""
    analyze(parse(src))


def test_semantic_supports_popcnt_clz_ctz_aliases_and_rotates():
    src = """
fn main() Int{
  x: u8 = 0b1001_0001u8;
  a = popcnt(x);
  b = clz(x);
  c = ctz(x);
  d: u8 = rotl(x, 1u8);
  e: u8 = rotr(d, 1u8);
  return a + b + c + (e as Int);
}
"""
    analyze(parse(src))


def test_semantic_rejects_static_shift_count_out_of_range():
    src = "fn main() Int{ x: u8 = 1 as u8; return (x << (8 as u8)) as Int; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "shift count 8 out of range for u8 in <<" in str(e)


def test_semantic_rejects_static_negative_shift_count():
    src = "fn main() Int{ x: Int = 1; return x >> -1; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "shift count -1 out of range for Int in >>" in str(e)


def test_semantic_rejects_bit_intrinsics_on_non_integer_type():
    src = "fn main() Int{ return countOnes(1.5); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "expects an integer argument" in str(e)


def test_semantic_rejects_rotates_on_non_integer_types():
    src = "fn main() Int{ return rotl(1.5, 1) as Int; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "expects integer arg 0" in str(e)


def test_semantic_rejects_maxval_on_non_integer_type():
    src = "fn main() Int{ x = maxVal(Float); return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "maxVal expects an integer type" in str(e)


def test_semantic_rejects_signed_i1_with_hint():
    src = "fn main() Int{ x: i1 = 0 as i1; return x as Int; }"
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
fn main() Int{ return 0; }
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
fn main() Int{ return 0; }
"""
    analyze(parse(src))


def test_call_of_non_function_reports_explicit_type_error():
    src = "fn main() Int{ return (1)(); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot call value of non-function type Int" in str(e)


def test_layout_query_semantics_for_type_and_value_forms():
    src = "struct P { a Int, b u8 } fn main() Int{ p = P(1, 2 as u8); return sizeof(P) + alignof(P) + size_of(p.a) + align_of(p.b); }"
    analyze(parse(src))


def test_layout_query_rejects_opaque_and_unsized_types():
    src = "fn main() Int{ return sizeof(String); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "not queryable" in str(e)


def test_mutable_borrow_blocks_shared_borrow():
    src = "fn main() Int{ mut x = 1; r = &mut x; s = &x; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot immutably borrow x while it is mutably borrowed" in str(e)


def test_shared_borrow_blocks_mutation():
    src = "fn main() Int{ mut x = 1; r = &x; x = 2; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot mutate x while it is immutably borrowed" in str(e)


def test_mutable_borrow_blocks_direct_use_of_owner():
    src = "fn main() Int{ mut x = 1; r = &mut x; return x; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot use x while it is mutably borrowed" in str(e)


def test_multiple_shared_borrows_are_allowed():
    src = "fn main() Int{ mut x = 1; a = &x; b = &x; return *a + *b; }"
    analyze(parse(src))


def test_mutable_borrow_requires_mutable_binding():
    src = "fn main() Int{ x = 1; r = &mut x; return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "cannot mutably borrow immutable binding x" in str(e)


def test_ref_return_without_ref_param_is_rejected():
    src = "fn bad() &Int{ x = 1; return &x; } fn main() Int{ return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "returns a reference but has no reference parameter" in str(e)


def test_ref_return_must_tie_to_ref_param():
    src = "fn f(xs &[Int]) &Int{ x = 1; r = &x; return r; } fn main() Int{ return 0; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "returned reference is not tied to an input reference parameter" in str(e)


def test_ref_return_alias_of_ref_param_is_allowed():
    src = "fn f(xs &Int) &Int{ y = xs; return y; } fn main() Int{ return 0; }"
    analyze(parse(src))


def test_use_after_move_is_rejected_for_non_copy_values():
    src = "struct S { v Int } fn main() Int{ a = S(1); b = a; return a.v; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "use-after-move of a" in str(e)


def test_drop_consumes_non_copy_values():
    src = "struct S { v Int } fn main() Int{ a = S(1); drop a; return a.v; }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "use-after-move of a" in str(e)


def test_drop_releases_alloc_owned_handle():
    src = "fn main() Int{ p = alloc(8); drop p; return 0; }"
    analyze(parse(src))


def test_copy_values_are_usable_after_assignment():
    src = "fn main() Int{ a = 7; b = a; return a + b; }"
    analyze(parse(src))


def test_slice_get_returns_option_type():
    src = "fn main() Int{ x: Option<Int> = [1, 2].get(0); return x ?? 0; }"
    analyze(parse(src))


def test_owned_internal_use_after_free_reports_exact_location():
    filename = "tmp/owned_use_after_free.astra"
    src = (
        "fn main() Int{\n"
        "  p = alloc(8);\n"
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
        "fn main() Int{\n"
        "  p = alloc(8);\n"
        "  q = p;\n"
        "  r = p;\n"
        "  return 0;\n"
        "}\n"
    )
    try:
        analyze(parse(src, filename=filename), filename=filename)
        assert False
    except SemanticError as e:
        assert str(e) == "SEM tmp/owned_use_after_move.astra:4:7: use-after-move of p"


def test_owned_internal_reassignment_leak_reports_exact_location():
    filename = "tmp/owned_reassign_leak.astra"
    src = (
        "fn main() Int{\n"
        "  mut p = alloc(8);\n"
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
    src = "fn main() Int{ return join(1); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "type mismatch for return" in str(e)


def test_any_explicit_downcast_is_allowed():
    src = "fn worker(x Int) Int{ return x; } fn main() Int{ t = spawn(worker, 1); return join(t) as Int; }"
    analyze(parse(src))


def test_calling_unsafe_fn_requires_unsafe_context():
    src = "unsafe fn danger() Int{ return 1; } fn main() Int{ return danger(); }"
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "requires unsafe context" in str(e)


def test_unsafe_block_allows_calling_unsafe_fn():
    src = "unsafe fn danger() Int{ return 1; } fn main() Int{ unsafe { return danger(); } }"
    analyze(parse(src))


def test_unsafe_fn_allows_calling_unsafe_fn():
    src = "unsafe fn danger() Int{ return 1; } unsafe fn main() Int{ return danger(); }"
    analyze(parse(src))


def test_spawn_rejects_non_send_argument_types():
    src = """
fn worker(x Any) Int{ return 0; }
fn main() Int{
  x = from_json("1");
  t = spawn(worker, x);
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
fn worker(v &Vec<Int>) Int{ return vec_len(*v); }
fn main() Int{
  v: Vec<Int> = vec_new() as Vec<Int>;
  t = spawn(worker, &v);
  return join(t) as Int;
}
"""
    try:
        analyze(parse(src))
        assert False
    except SemanticError as e:
        assert "spawn arg 1 requires Send" in str(e)
