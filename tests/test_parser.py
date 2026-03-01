from astra.ast import (
    AlignOfTypeExpr,
    AlignOfValueExpr,
    AssignStmt,
    AwaitExpr,
    Binary,
    BreakStmt,
    CastExpr,
    ContinueStmt,
    DeferStmt,
    DropStmt,
    EnumDecl,
    ExternFnDecl,
    FieldExpr,
    FnDecl,
    ForStmt,
    ImportDecl,
    IndexExpr,
    LetStmt,
    SizeOfTypeExpr,
    SizeOfValueExpr,
    StructDecl,
    TypeAliasDecl,
    Unary,
)
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


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


def test_parse_option_type_sugar():
    src = "fn maybe(x: Int?) -> Int? { let y: Int? = none; return y; } fn main() -> Int { return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    assert fn.params == [("x", "Option<Int>")]
    assert fn.ret == "Option<Int>"


def test_parse_owned_and_borrowed_text_buffer_types():
    src = """
type Bytes = Vec<u8>;
fn view(s: &str, b: Bytes, xs: Vec<i16>, sl: &[u8]) -> Void { return; }
"""
    prog = parse(src)
    assert isinstance(prog.items[0], TypeAliasDecl)
    fn = prog.items[1]
    assert isinstance(fn, FnDecl)
    assert fn.params == [("s", "&str"), ("b", "Bytes"), ("xs", "Vec<i16>"), ("sl", "&[u8]")]
    assert fn.ret == "Void"


def test_parse_defer_and_coalesce():
    src = """
fn main() -> Int {
  defer print("done");
  let x: Option<Int> = none;
  let y = x ?? 7;
  return y;
}
"""
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0], DeferStmt)
    assert isinstance(fn.body[1], LetStmt)
    assert isinstance(fn.body[2], LetStmt)
    assert isinstance(fn.body[2].expr, Binary)
    assert fn.body[2].expr.op == "??"


def test_parse_drop_stmt():
    src = "fn main() -> Int { drop print(1); return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0], DropStmt)


def test_parse_mutable_borrow_unary_expression():
    src = "fn main() -> Int { let mut x = 1; let r = &mut x; return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[1], LetStmt)
    assert isinstance(fn.body[1].expr, Unary)
    assert fn.body[1].expr.op == "&mut"


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


def test_nil_keyword_is_rejected():
    try:
        analyze(parse("fn main() -> Int { let x = nil; return 0; }"))
        assert False
    except SemanticError as e:
        assert "undefined name nil" in str(e)


def test_parse_bitwise_shift_cast_and_layout_queries():
    src = """
fn main() -> Int {
  let x: u8 = 3 as u8;
  let y: u8 = (x << (1 as u8)) | (1 as u8);
  let a = sizeof(u16);
  let b = alignof(u16);
  let c = size_of(y);
  let d = align_of(y);
  return (y as Int) + a + b + c + d;
}
"""
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0].expr, CastExpr)
    assert isinstance(fn.body[1].expr, Binary)
    assert isinstance(fn.body[2].expr, SizeOfTypeExpr)
    assert isinstance(fn.body[3].expr, AlignOfTypeExpr)
    assert isinstance(fn.body[4].expr, SizeOfValueExpr)
    assert isinstance(fn.body[5].expr, AlignOfValueExpr)


def test_parse_dynamic_integer_type_names():
    src = "fn widen(x: u4, y: i127) -> u4 { return x; }"
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn, FnDecl)
    assert fn.params == [("x", "u4"), ("y", "i127")]
    assert fn.ret == "u4"


def test_parse_integer_literal_type_suffix():
    src = "fn main() -> Int { let x: u4 = 15u4; return x as Int; }"
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0], LetStmt)
    assert isinstance(fn.body[0].expr, CastExpr)
    assert fn.body[0].expr.type_name == "u4"
