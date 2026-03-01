import pytest

from astra.ast import LetStmt
from astra.formatter import fmt
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


INT_WIDTH_TYPES = ["i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "i128", "u128", "isize", "usize"]


def test_parse_fixed_typed_and_inferred_bindings():
    src = """
fn main() -> Int {
  fixed a = 1;
  fixed b: i16 = 2;
  return a + b;
}
"""
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0], LetStmt)
    assert fn.body[0].fixed
    assert fn.body[0].type_name is None
    assert isinstance(fn.body[1], LetStmt)
    assert fn.body[1].fixed
    assert fn.body[1].type_name == "i16"


def test_parse_rejects_fixed_mut_binding():
    src = "fn main() -> Int { fixed mut x = 1; return 0; }"
    with pytest.raises(ParseError, match="fixed bindings cannot be mutable"):
        parse(src)


def test_semantic_rejects_assignment_to_fixed_binding():
    src = """
fn main() -> Int {
  fixed x = 1;
  x = 2;
  return x;
}
"""
    with pytest.raises(SemanticError, match="cannot assign to fixed binding x"):
        analyze(parse(src))


def test_semantic_allows_shadowing_fixed_binding_with_mutable_let():
    src = """
fn main() -> Int {
  fixed x = 1;
  if true {
    let mut x = 2;
    x = 3;
  }
  return x;
}
"""
    analyze(parse(src))


@pytest.mark.parametrize("ty", INT_WIDTH_TYPES)
def test_fixed_typed_binding_accepts_integer_literal(ty: str):
    src = f"""
fn main() -> Int {{
  fixed value: {ty} = 1;
  return 0;
}}
"""
    analyze(parse(src))


@pytest.mark.parametrize("ty", INT_WIDTH_TYPES)
def test_fixed_inferred_binding_can_assign_into_typed_integer_width(ty: str):
    src = f"""
fn main() -> Int {{
  fixed value = 1;
  let casted: {ty} = value;
  return casted;
}}
"""
    analyze(parse(src))


@pytest.mark.parametrize("ty", INT_WIDTH_TYPES)
def test_integer_width_types_work_in_numeric_expressions(ty: str):
    src = f"""
fn bump(x: {ty}) -> Int {{
  let y: {ty} = x + (1 as {ty});
  return (y * (2 as {ty})) as Int;
}}

fn main() -> Int {{
  return bump(4 as {ty});
}}
"""
    analyze(parse(src))


@pytest.mark.parametrize("ty", INT_WIDTH_TYPES)
def test_fixed_in_for_initializer_is_immutable(ty: str):
    src = f"""
fn main() -> Int {{
  for fixed i: {ty} = 0 as {ty}; i < (2 as {ty}); i += (1 as {ty}) {{
    print(i);
  }}
  return 0;
}}
"""
    with pytest.raises(SemanticError, match="cannot assign to fixed binding i"):
        analyze(parse(src))


@pytest.mark.parametrize("ty", INT_WIDTH_TYPES)
def test_fixed_typed_binding_rejects_float_literal(ty: str):
    src = f"""
fn main() -> Int {{
  fixed value: {ty} = 1.5;
  return 0;
}}
"""
    with pytest.raises(SemanticError, match="type mismatch"):
        analyze(parse(src))


def test_formatter_preserves_fixed_syntax():
    src = "fn main() -> Int { fixed x:i8=1; return x; }\n"
    out = fmt(src)
    assert "fixed x: i8 = 1;" in out
    assert fmt(out) == out
