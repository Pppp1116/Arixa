from astra.ast import (
    AssignStmt,
    AwaitExpr,
    Binary,
    BreakStmt,
    ContinueStmt,
    DeferStmt,
    EnumDecl,
    ExternFnDecl,
    FieldExpr,
    FnDecl,
    ForStmt,
    ImportDecl,
    IndexExpr,
    LetStmt,
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


def test_parse_extern_and_async_await():
    src = """
/// ffi sum
unsafe extern "libc.so.6" fn c_add(a Int, b Int) -> Int;
async fn worker() -> Int { return await c_add(1, 2); }
fn main() -> Int { return 0; }
"""
    prog = parse(src)
    ext = prog.items[0]
    fn = prog.items[1]
    assert isinstance(ext, ExternFnDecl)
    assert ext.unsafe
    assert ext.doc == "ffi sum"
    assert isinstance(fn, FnDecl)
    assert fn.async_fn
    assert isinstance(fn.body[0].expr, AwaitExpr)


def test_parse_colon_typed_params_and_fields():
    src = """
struct Vec2 { x: Int, y: Int, }
fn add(a: Int, b: Int,) -> Int { return a + b; }
fn main() -> Int { return add(1, 2); }
"""
    prog = parse(src)
    st = prog.items[0]
    fn = prog.items[1]
    assert isinstance(st, StructDecl)
    assert st.fields == [("x", "Int"), ("y", "Int")]
    assert isinstance(fn, FnDecl)
    assert fn.params == [("a", "Int"), ("b", "Int")]


def test_parse_defer_and_coalesce():
    src = """
fn main() -> Int {
  defer print("done");
  let x = nil ?? 7;
  return x;
}
"""
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0], DeferStmt)
    assert isinstance(fn.body[1], LetStmt)
    assert isinstance(fn.body[1].expr, Binary)
    assert fn.body[1].expr.op == "??"


def test_parse_impl_fn_specializations():
    src = """
impl fn sum(x T) -> T { return x; }
impl fn sum(x Int) -> Int { return x; }
fn main() -> Int { return sum(1); }
"""
    prog = parse(src)
    assert isinstance(prog.items[0], FnDecl) and prog.items[0].is_impl
    assert isinstance(prog.items[1], FnDecl) and prog.items[1].is_impl


def test_doc_comment_attaches_to_next_decl():
    prog = parse("/// hello\nfn main() -> Int { return 0; }\n")
    assert isinstance(prog.items[0], FnDecl)
    assert prog.items[0].doc == "hello"


def test_multi_error_recovery_collects_multiple():
    bad = "fn main() -> Int { let = 1; if { return 0 } let x = ; }"
    try:
        parse(bad)
        assert False, "expected ParseError"
    except ParseError as e:
        lines = str(e).splitlines()
        assert len(lines) >= 2
        assert any(line.startswith("PARSE") for line in lines)
