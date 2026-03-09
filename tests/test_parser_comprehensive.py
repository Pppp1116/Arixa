"""Comprehensive parser tests aligned with current ASTRA grammar."""

import pytest

from astra.ast import (
    AssignStmt,
    Binary,
    CastExpr,
    EnumDecl,
    ExternFnDecl,
    FieldExpr,
    FnDecl,
    ForStmt,
    GuardedPattern,
    IfStmt,
    ImportDecl,
    LetStmt,
    MatchStmt,
    Name,
    OrPattern,
    RangeExpr,
    StructDecl,
    TraitDecl,
    TypeAliasDecl,
    WhileStmt,
)
from astra.parser import ParseError, parse


def test_expression_precedence_and_calls() -> None:
    prog = parse("fn main() Int{ x = 1 + 2 * 3; y = add(x, 4); return y; }")
    fn = prog.items[0]
    assert isinstance(fn, FnDecl)
    assert isinstance(fn.body[0], LetStmt)
    expr = fn.body[0].expr
    assert isinstance(expr, Binary)
    assert expr.op == "+"
    assert isinstance(expr.right, Binary)
    assert expr.right.op == "*"


def test_cast_and_nullable_types() -> None:
    prog = parse("fn main() Int{ x: Int? = none; y = (x ?? 1) as Int; return y; }")
    fn = prog.items[0]
    assert isinstance(fn, FnDecl)
    assert fn.ret == "Int"
    assert fn.body[0].type_name == "Int | none"
    assert isinstance(fn.body[1].expr, CastExpr)


def test_if_while_and_assignments() -> None:
    prog = parse("fn main() Int{ mut x = 0; while x < 3 { x += 1; } if x == 3 { return 1; } else { return 0; } }")
    fn = prog.items[0]
    assert isinstance(fn.body[0], LetStmt)
    assert isinstance(fn.body[1], WhileStmt)
    assert isinstance(fn.body[1].body[0], AssignStmt)
    assert isinstance(fn.body[2], IfStmt)


def test_for_ranges_and_iterables() -> None:
    prog = parse("fn main() Int{ mut s = 0; for i in 1..=3 { s += i; } return s; }")
    fn = prog.items[0]
    loop = fn.body[1]
    assert isinstance(loop, ForStmt)
    assert loop.var == "i"
    assert isinstance(loop.iterable, RangeExpr)
    assert loop.iterable.inclusive


def test_match_or_pattern_with_guard() -> None:
    src = "fn main() Int{ x = 2; match x { 1 | 2 if x == 2 => { return 1; }, _ => { return 0; } } return 0; }"
    prog = parse(src)
    fn = prog.items[0]
    m = fn.body[1]
    assert isinstance(m, MatchStmt)
    pat = m.arms[0][0]
    assert isinstance(pat, GuardedPattern)
    assert isinstance(pat.pattern, OrPattern)


def test_top_level_declarations_parse() -> None:
    src = """
import std.io as io;
@derive(Serialize)
struct Point { x Int, y Int }
enum Mode { A, B }
trait Show { fn show(x Self) String; }
type Score = Int;
fn main() Int{ return 0; }
"""
    prog = parse(src)
    assert isinstance(prog.items[0], ImportDecl)
    assert isinstance(prog.items[1], StructDecl)
    assert isinstance(prog.items[2], EnumDecl)
    assert isinstance(prog.items[3], TraitDecl)
    assert isinstance(prog.items[4], TypeAliasDecl)
    assert isinstance(prog.items[5], FnDecl)


def test_extern_and_gpu_fn_parse() -> None:
    src = """
@link("c")
extern fn printf(fmt *u8, ...) i32;
gpu fn k(xs GpuSlice<Float>) Void { return; }
fn main() Int{ return 0; }
"""
    prog = parse(src)
    assert isinstance(prog.items[0], ExternFnDecl)
    assert prog.items[0].is_variadic
    assert isinstance(prog.items[1], FnDecl)
    assert prog.items[1].gpu_kernel


def test_rejects_legacy_arrow_return_syntax() -> None:
    with pytest.raises(ParseError):
        parse("fn main() -> Int { return 0; }")


def test_rejects_c_style_for_loop() -> None:
    with pytest.raises(ParseError):
        parse("fn main() Int{ for i = 0; i < 3; i += 1 { } return 0; }")


def test_import_string_path_parse() -> None:
    prog = parse('import "../shared/util.arixa"; fn main() Int{ return 0; }')
    imp = prog.items[0]
    assert isinstance(imp, ImportDecl)
    assert imp.source == "../shared/util.arixa"


def test_field_access_expression_parses() -> None:
    prog = parse("fn main() Int{ p = Point(1,2); return p.x; }")
    fn = prog.items[0]
    ret = fn.body[-1]
    assert isinstance(ret.expr, FieldExpr)
