from astra.parser import parse
from astra.semantic import analyze, SemanticError


def test_parse_new_binding_forms_and_set() -> None:
    src = """
fn main() Int{
  x = 1;
  mut y: i32 = 2;
  x = 3;
  set y += 1;
  return y as Int;
}
"""
    prog = parse(src)
    fn = prog.items[0]
    assert len(fn.body) == 5
    assert fn.body[0].name == "x"
    assert fn.body[0].reassign_if_exists is True
    assert fn.body[1].mut is True
    assert fn.body[3].explicit_set is True


def test_semantic_rejects_assign_to_immutable_binding() -> None:
    src = "fn main() Int{ x = 1; x = 2; return x; }"
    try:
        analyze(parse(src))
    except SemanticError as err:
        assert "cannot assign to immutable binding x" in str(err)
    else:
        raise AssertionError("expected immutable reassignment error")


def test_semantic_accepts_mutable_reassignment_dual_mode() -> None:
    src = "fn main() Int{ mut x: i32 = 1; x = 2; set x += 1; return x as Int; }"
    analyze(parse(src))


def test_nullable_union_coalesce() -> None:
    src = "fn main() Int{ name: String | none = none; v = name ?? \"x\"; return len(v); }"
    analyze(parse(src))


def test_try_operator_postfix_bang_union() -> None:
    src = """
fn parse(v Int) Int | ParseError{
  return v;
}
fn wrap(v Int) Int | ParseError{
  out = parse(v)!;
  return out;
}
fn main() Int{ return 0; }
"""
    analyze(parse(src))
