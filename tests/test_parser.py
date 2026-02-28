from astra.ast import (
    AssignStmt,
    Binary,
    BreakStmt,
    ContinueStmt,
    EnumDecl,
    FieldExpr,
    FnDecl,
    ForStmt,
    ImportDecl,
    IndexExpr,
    LetStmt,
    Name,
    StructDecl,
    Unary,
)
from astra.parser import ParseError, parse


def test_precedence_and_unary_and_chained_postfix():
    prog = parse("fn main() -> Int { let x = 1 + 2 * 3; let y = -x; let z = a.b[0].c; return 0; }")
    fn = prog.items[0]
    expr = fn.body[0].expr
    assert isinstance(expr, Binary)
    assert expr.op == "+"
    assert isinstance(expr.right, Binary)
    assert expr.right.op == "*"

    assert isinstance(fn.body[1].expr, Unary)
    assert isinstance(fn.body[2].expr, FieldExpr)
    assert isinstance(fn.body[2].expr.obj, IndexExpr)


def test_for_break_continue_import_struct_enum_mut_pub_assign():
    src = """
import stdlib::io as io;
pub struct Point { x Int, y Int }
enum Color { Red, Green, Blue }
pub fn main() -> Int {
  let mut x = 0;
  for ; x < 10; x += 1 {
    if x == 5 { break; }
    continue;
  }
  x = 5;
  return 0;
}
"""
    prog = parse(src)
    assert isinstance(prog.items[0], ImportDecl)
    assert isinstance(prog.items[1], StructDecl)
    assert isinstance(prog.items[2], EnumDecl)
    fn = prog.items[3]
    assert isinstance(fn, FnDecl) and fn.pub
    assert isinstance(fn.body[0], LetStmt) and fn.body[0].mut
    assert isinstance(fn.body[1], ForStmt)
    assert any(isinstance(s, BreakStmt) for s in fn.body[1].body[0].then_body)
    assert any(isinstance(s, ContinueStmt) for s in fn.body[1].body)
    assert isinstance(fn.body[2], AssignStmt) and fn.body[2].op == "="


def test_multi_error_recovery_collects_multiple():
    bad = "fn main() -> Int { let = 1; if { return 0 } let x = ; }"
    try:
        parse(bad)
        assert False, "expected ParseError"
    except ParseError as e:
        lines = str(e).splitlines()
        assert len(lines) >= 2
