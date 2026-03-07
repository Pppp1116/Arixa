from astra.ast import (
    BitSizeOfTypeExpr,
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
    GuardedPattern,
    ImportDecl,
    IndexExpr,
    LetStmt,
    Literal,
    MatchStmt,
    MaxValTypeExpr,
    MinValTypeExpr,
    Name,
    OrPattern,
    RangeExpr,
    SizeOfTypeExpr,
    SizeOfValueExpr,
    StructDecl,
    TraitDecl,
    TypeAliasDecl,
    TryExpr,
    Unary,
    UnsafeStmt,
    WildcardPattern,
)
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


def test_precedence_and_unary_and_chained_postfix():
    prog = parse("fn main() Int{ x = 1 + 2 * 3; y = -x; z = a.b[0].c; return 0; }")
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
pub fn main() Int{
  mut stop = 5;
  for x in 0..10 {
    if x == stop { break; }
    continue;
  }
  stop = 7;
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
    assert isinstance(fn.body[2], LetStmt) and fn.body[2].reassign_if_exists


def test_parse_range_for_builds_for_in_range_expr():
    src = """
fn main() Int{
  mut total = 0;
  for i in 1..4 {
    total += i;
  }
  return total;
}
"""
    prog = parse(src)
    fn = prog.items[0]
    loop = fn.body[1]
    assert isinstance(loop, ForStmt)
    assert loop.var == "i"
    assert isinstance(loop.iterable, RangeExpr)
    assert isinstance(loop.iterable.start, Literal) and loop.iterable.start.value == 1
    assert isinstance(loop.iterable.end, Literal) and loop.iterable.end.value == 4
    assert not loop.iterable.inclusive


def test_parse_range_for_inclusive_uses_lte_condition():
    src = "fn main() Int{ for i in 0..=2 { } return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    loop = fn.body[0]
    assert isinstance(loop, ForStmt)
    assert isinstance(loop.iterable, RangeExpr)
    assert loop.iterable.inclusive


def test_parse_for_rejects_c_style_loop():
    bad = "fn main() Int{ for i = 0; i < 3; i += 1 { } return 0; }"
    try:
        parse(bad)
        assert False
    except ParseError as e:
        assert "for expects `for <ident> in <expr> { ... }`" in str(e)


def test_parse_match_accepts_wildcard_pattern():
    src = "fn main() Int{ x = 1; match x { _ => { return 2; } } return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    m = fn.body[1]
    assert isinstance(m, MatchStmt)
    assert isinstance(m.arms[0][0], WildcardPattern)


def test_parse_match_or_pattern_and_guard():
    src = """
fn main() Int{
  x = 2;
  match x {
    1 | 2 if x == 2 => { return 7; }
    _ => { return 0; }
  }
  return 0;
}
"""
    prog = parse(src)
    fn = prog.items[0]
    m = fn.body[1]
    assert isinstance(m, MatchStmt)
    pat = m.arms[0][0]
    assert isinstance(pat, GuardedPattern)
    assert isinstance(pat.pattern, OrPattern)
    assert len(pat.pattern.patterns) == 2


def test_parse_trait_where_and_implicit_satisfaction():
    src = """
trait Show {
  fn show(x Self) String;
}

fn show(x Int) String { return "ok"; }

fn wrap<T>(x T) T where T: Show{
  return x;
}
"""
    prog = parse(src)
    assert isinstance(prog.items[0], TraitDecl)
    assert prog.items[0].name == "Show"
    fn = prog.items[2]
    assert isinstance(fn, FnDecl)
    assert fn.generics == ["T"]
    assert fn.where_bounds == [("T", "Show")]


def test_parse_inline_generic_bounds_accepts_space_and_colon_forms():
    src = """
trait Show { fn show(x Self) String; }
fn show(x Int) String { return "ok"; }
fn a<T Show>(x T) T{ return x; }
fn b<U: Show>(x U) U{ return x; }
"""
    prog = parse(src)
    fa = prog.items[2]
    fb = prog.items[3]
    assert isinstance(fa, FnDecl)
    assert isinstance(fb, FnDecl)
    assert fa.generics == ["T"]
    assert fb.generics == ["U"]
    assert fa.where_bounds == [("T", "Show")]
    assert fb.where_bounds == [("U", "Show")]


def test_parse_derive_attribute_on_struct_and_enum():
    src = """
@derive(Serialize, Deserialize)
struct User { name str, age i32 }
@derive(Serialize)
enum Mode { A, B }
fn main() Int{ return 0; }
"""
    prog = parse(src)
    st = prog.items[0]
    en = prog.items[1]
    assert isinstance(st, StructDecl)
    assert isinstance(en, EnumDecl)
    assert st.derives == ["Serialize", "Deserialize"]
    assert en.derives == ["Serialize"]


def test_import_supports_dotted_module_and_string_forms():
    src = """
import std.io as io;
import "../shared/util.astra";
fn main() Int{ return 0; }
"""
    prog = parse(src)
    imp_mod = prog.items[0]
    imp_str = prog.items[1]
    assert isinstance(imp_mod, ImportDecl)
    assert imp_mod.path == ["std", "io"]
    assert imp_mod.source is None
    assert imp_mod.alias == "io"
    assert isinstance(imp_str, ImportDecl)
    assert imp_str.path == []
    assert imp_str.source == "../shared/util.astra"


def test_parse_extern_and_async_await():
    src = """
/// ffi sum
unsafe extern "libc.so.6" fn c_add(a Int, b Int) Int;
async fn worker() Int{ return await c_add(1, 2); }
fn main() Int{ return 0; }
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


def test_parse_linked_variadic_extern_fn():
    src = '@link("c") extern fn printf(fmt *u8, ...) i32;'
    prog = parse(src)
    ext = prog.items[0]
    assert isinstance(ext, ExternFnDecl)
    assert ext.link_libs == ["c"]
    assert ext.params == [("fmt", "*u8")]
    assert ext.is_variadic


def test_parse_unsafe_fn_and_block():
    src = """
unsafe fn poke(x Int) Int{ return x; }
fn main() Int{
  unsafe {
    y = poke(7);
    return y;
  }
}
"""
    prog = parse(src)
    worker = prog.items[0]
    main = prog.items[1]
    assert isinstance(worker, FnDecl)
    assert worker.unsafe
    assert isinstance(main, FnDecl)
    assert isinstance(main.body[0], UnsafeStmt)


def test_parse_colon_typed_params_and_fields():
    src = """
struct Vec2 { x: Int, y: Int, }
fn add(a Int, b Int,) Int{ return a + b; }
fn main() Int{ return add(1, 2); }
"""
    prog = parse(src)
    st = prog.items[0]
    fn = prog.items[1]
    assert isinstance(st, StructDecl)
    assert st.fields == [("x", "Int"), ("y", "Int")]
    assert isinstance(fn, FnDecl)
    assert fn.params == [("a", "Int"), ("b", "Int")]


def test_parse_option_type_sugar():
    src = "fn maybe(x Int?) Int?{ y: Int? = none; return y; } fn main() Int{ return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    assert fn.params == [("x", "Int | none")]
    assert fn.ret == "Int | none"


def test_parse_owned_and_borrowed_text_buffer_types():
    src = """
type Bytes = Vec<u8>;
fn view(s &str, b Bytes, xs Vec<i16>, sl &[u8]) Void{ return; }
"""
    prog = parse(src)
    assert isinstance(prog.items[0], TypeAliasDecl)
    fn = prog.items[1]
    assert isinstance(fn, FnDecl)
    assert fn.params == [("s", "&str"), ("b", "Bytes"), ("xs", "Vec<i16>"), ("sl", "&[u8]")]
    assert fn.ret == "Void"


def test_parse_defer_and_coalesce():
    src = """
fn main() Int{
  defer print("done");
  x: Option<Int> = none;
  y = x ?? 7;
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


def test_parse_try_postfix_operator():
    src = """
fn helper(v Option<Int>) Option<Int>{
  x = v!;
  return x;
}
fn main() Int{ return 0; }
"""
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0], LetStmt)
    assert isinstance(fn.body[0].expr, TryExpr)


def test_parse_accepts_multiline_string_literal():
    src = """
fn main() Int{
  s = \"\"\"a
b\"\"\";
  return 0;
}
"""
    prog = parse(src)
    assert isinstance(prog.items[0], FnDecl)


def test_parse_drop_stmt():
    src = "fn main() Int{ drop print(1); return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0], DropStmt)


def test_parse_mutable_borrow_unary_expression():
    src = "fn main() Int{ mut x = 1; r = &mut x; return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[1], LetStmt)
    assert isinstance(fn.body[1].expr, Unary)
    assert fn.body[1].expr.op == "&mut"


def test_parse_overload_specializations():
    src = """
fn sum(x T) T{ return x; }
fn sum(x Int) Int{ return x; }
fn main() Int{ return sum(1); }
"""
    prog = parse(src)
    assert isinstance(prog.items[0], FnDecl)
    assert isinstance(prog.items[1], FnDecl)


def test_doc_comment_attaches_to_next_decl():
    prog = parse("/// hello\nfn main() Int{ return 0; }\n")
    assert isinstance(prog.items[0], FnDecl)
    assert prog.items[0].doc == "hello"


def test_multi_error_recovery_collects_multiple():
    bad = "fn main() Int{ = 1; if { return 0 } x = ; }"
    try:
        parse(bad)
        assert False, "expected ParseError"
    except ParseError as e:
        lines = str(e).splitlines()
        assert len(lines) >= 2
        assert any(line.startswith("PARSE") for line in lines)


def test_parse_deep_nesting_reports_parse_error_with_span():
    nested = "(" * 120 + "1" + ")" * 119
    bad = f"fn main() Int{{ x = {nested}; return 0; }}"
    try:
        parse(bad, filename="deep.astra")
        assert False, "expected ParseError"
    except ParseError as e:
        line = str(e).splitlines()[0]
        assert line.startswith("PARSE deep.astra:1:")


def test_nil_keyword_is_rejected():
    try:
        analyze(parse("fn main() Int{ x = nil; return 0; }"))
        assert False
    except SemanticError as e:
        assert "undefined name nil" in str(e)


def test_parse_bitwise_shift_cast_and_layout_queries():
    src = """
fn main() Int{
  x: u8 = 3 as u8;
  y: u8 = (x << (1 as u8)) | (1 as u8);
  a = sizeof(u16);
  b = alignof(u16);
  c = size_of(y);
  d = align_of(y);
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
    src = "fn widen(x u4, y i127) u4{ return x; }"
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn, FnDecl)
    assert fn.params == [("x", "u4"), ("y", "i127")]
    assert fn.ret == "u4"


def test_parse_integer_literal_type_suffix():
    src = "fn main() Int{ x: u4 = 15u4; return x as Int; }"
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0], LetStmt)
    assert isinstance(fn.body[0].expr, CastExpr)
    assert fn.body[0].expr.type_name == "u4"


def test_parse_prefixed_integer_literals_and_suffixes():
    src = "fn main() Int{ a = 0xFF_FF; b = 0b1010_0101u16; return (a as Int) + (b as Int); }"
    prog = parse(src)
    fn = prog.items[0]
    assert fn.body[0].expr.value == 65535
    assert isinstance(fn.body[1].expr, CastExpr)
    assert fn.body[1].expr.type_name == "u16"


def test_parse_packed_struct_attribute():
    src = "@packed struct Header { version: u4, flags: u3, enabled: u1 }"
    prog = parse(src)
    st = prog.items[0]
    assert isinstance(st, StructDecl)
    assert st.packed
    assert st.fields == [("version", "u4"), ("flags", "u3"), ("enabled", "u1")]


def test_parse_bit_intrinsics_with_type_arguments():
    src = """
fn main() Int{
  a = bitSizeOf(u3);
  b = maxVal(u4);
  c = minVal(i4);
  return a + (b as Int) + (c as Int);
}
"""
    prog = parse(src)
    fn = prog.items[0]
    assert isinstance(fn.body[0].expr, BitSizeOfTypeExpr)
    assert isinstance(fn.body[1].expr, MaxValTypeExpr)
    assert isinstance(fn.body[2].expr, MinValTypeExpr)
