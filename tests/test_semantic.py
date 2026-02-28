from astra.parser import parse
from astra.semantic import SemanticError, analyze


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


def test_missing_import_is_semantic_error():
    src = "import nope::missing; fn main() -> Int { return 0; }"
    try:
        analyze(parse(src), filename="/tmp/input.astra")
        assert False
    except SemanticError as e:
        assert "cannot resolve import" in str(e)


def test_freestanding_allows_no_main():
    src = "fn kernel() -> Int { return 0; }"
    analyze(parse(src), freestanding=True)


def test_coalesce_type_inference():
    src = "fn main() -> Int { let x: Int = nil ?? 4; return x; }"
    analyze(parse(src))


def test_defer_is_semantically_valid():
    src = 'fn main() -> Int { defer print("bye"); return 0; }'
    analyze(parse(src))


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
        assert "ambiguous impl" in str(e)
