from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from astra.ast import (
    AlignOfTypeExpr,
    ArrayLit,
    AssignStmt,
    AwaitExpr,
    Binary,
    BreakStmt,
    Call,
    CastExpr,
    ComptimeStmt,
    ContinueStmt,
    DeferStmt,
    DropStmt,
    EnumDecl,
    ExprStmt,
    ExternFnDecl,
    FieldExpr,
    FnDecl,
    ForStmt,
    IfStmt,
    ImportDecl,
    IndexExpr,
    LetStmt,
    MatchStmt,
    MaxValTypeExpr,
    MinValTypeExpr,
    Name,
    Program,
    ReturnStmt,
    SizeOfTypeExpr,
    StructDecl,
    StructLit,
    TypeAliasDecl,
    TypeAnnotated,
    Unary,
    UnsafeStmt,
    WhileStmt,
    BitSizeOfTypeExpr,
    SizeOfValueExpr,
    AlignOfValueExpr,
)

_PRIMITIVE_TYPE_NAMES = {
    "Int",
    "isize",
    "usize",
    "Float",
    "f32",
    "f64",
    "String",
    "str",
    "Bool",
    "Any",
    "Void",
    "Never",
    "Bytes",
    "Option",
    "Result",
    "Vec",
}

_TYPE_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class ReachabilityResult:
    reachable_functions: set[str]
    reachable_types: set[str]


def prune_unreachable_items(prog: Program, *, entry: str = "main") -> Program:
    fn_items = [item for item in prog.items if isinstance(item, (FnDecl, ExternFnDecl))]
    fn_by_key: dict[str, FnDecl | ExternFnDecl] = {}
    fn_name_to_keys: dict[str, set[str]] = {}
    for decl in fn_items:
        key = _fn_key(decl)
        fn_by_key[key] = decl
        fn_name_to_keys.setdefault(decl.name, set()).add(key)

    struct_map = {item.name: item for item in prog.items if isinstance(item, StructDecl)}
    enum_map = {item.name: item for item in prog.items if isinstance(item, EnumDecl)}
    alias_map = {item.name: item for item in prog.items if isinstance(item, TypeAliasDecl)}
    type_names = set(struct_map) | set(enum_map) | set(alias_map)

    roots = set(fn_name_to_keys.get(entry, set()))
    if entry != "_start":
        roots |= fn_name_to_keys.get("_start", set())

    reachable_fns: set[str] = set()
    reachable_types: set[str] = set()
    dynamic_calls = False

    fn_work = list(roots)
    while fn_work:
        key = fn_work.pop()
        if key in reachable_fns:
            continue
        decl = fn_by_key.get(key)
        if decl is None:
            continue
        reachable_fns.add(key)
        newly_used_types: set[str] = set()
        _collect_types_from_signature(decl, newly_used_types, type_names)
        _mark_new_types(newly_used_types, reachable_types, struct_map, enum_map, alias_map, type_names)

        if isinstance(decl, FnDecl):
            called_fns, used_types, saw_dynamic = _scan_fn_body(decl, fn_name_to_keys, enum_map, type_names)
            dynamic_calls = dynamic_calls or saw_dynamic
            _mark_new_types(used_types, reachable_types, struct_map, enum_map, alias_map, type_names)
            for called in called_fns:
                if called in fn_by_key and called not in reachable_fns:
                    fn_work.append(called)

    if dynamic_calls:
        reachable_fns = set(fn_by_key.keys())

    kept: list[Any] = []
    for item in prog.items:
        if isinstance(item, ImportDecl):
            continue
        if isinstance(item, (FnDecl, ExternFnDecl)):
            if _fn_key(item) in reachable_fns:
                kept.append(item)
            continue
        if isinstance(item, (StructDecl, EnumDecl, TypeAliasDecl)):
            if item.name in reachable_types:
                kept.append(item)
            continue
        kept.append(item)
    prog.items = kept
    return prog


def _fn_key(decl: FnDecl | ExternFnDecl) -> str:
    return decl.symbol if isinstance(decl, FnDecl) and decl.symbol else decl.name


def _collect_types_from_signature(decl: FnDecl | ExternFnDecl, out: set[str], known_types: set[str]) -> None:
    for _, pty in decl.params:
        out.update(_extract_known_types(pty, known_types))
    out.update(_extract_known_types(decl.ret, known_types))


def _extract_known_types(typ: str, known_types: set[str]) -> set[str]:
    out: set[str] = set()
    for ident in _TYPE_IDENT_RE.findall(str(typ)):
        if ident in known_types and ident not in _PRIMITIVE_TYPE_NAMES:
            out.add(ident)
    return out


def _mark_new_types(
    pending: set[str],
    reachable_types: set[str],
    struct_map: dict[str, StructDecl],
    enum_map: dict[str, EnumDecl],
    alias_map: dict[str, TypeAliasDecl],
    known_types: set[str],
) -> None:
    work = list(pending)
    while work:
        typ = work.pop()
        if typ in reachable_types:
            continue
        reachable_types.add(typ)
        if typ in struct_map:
            for _, fty in struct_map[typ].fields:
                for t in _extract_known_types(fty, known_types):
                    if t not in reachable_types:
                        work.append(t)
        if typ in enum_map:
            for _, payload in enum_map[typ].variants:
                for pty in payload:
                    for t in _extract_known_types(pty, known_types):
                        if t not in reachable_types:
                            work.append(t)
        if typ in alias_map:
            for t in _extract_known_types(alias_map[typ].target, known_types):
                if t not in reachable_types:
                    work.append(t)


def _scan_fn_body(
    fn: FnDecl,
    fn_name_to_keys: dict[str, set[str]],
    enum_map: dict[str, EnumDecl],
    known_types: set[str],
) -> tuple[set[str], set[str], bool]:
    called: set[str] = set()
    used_types: set[str] = set()
    dynamic_calls = False

    for st in fn.body:
        c, t, dyn = _scan_stmt(st, fn_name_to_keys, enum_map, known_types)
        called |= c
        used_types |= t
        dynamic_calls = dynamic_calls or dyn
    return called, used_types, dynamic_calls


def _scan_stmt(st: Any, fn_name_to_keys: dict[str, set[str]], enum_map: dict[str, EnumDecl], known_types: set[str]) -> tuple[set[str], set[str], bool]:
    called: set[str] = set()
    used_types: set[str] = set()
    dynamic = False
    if isinstance(st, LetStmt):
        if st.type_name is not None:
            used_types |= _extract_known_types(st.type_name, known_types)
        c, t, d = _scan_expr(st.expr, fn_name_to_keys, enum_map, known_types)
        return called | c, used_types | t, dynamic or d
    if isinstance(st, AssignStmt):
        c1, t1, d1 = _scan_expr(st.target, fn_name_to_keys, enum_map, known_types)
        c2, t2, d2 = _scan_expr(st.expr, fn_name_to_keys, enum_map, known_types)
        return c1 | c2, t1 | t2, d1 or d2
    if isinstance(st, (ExprStmt, DropStmt, ReturnStmt, DeferStmt)):
        expr = st.expr if not isinstance(st, ReturnStmt) else st.expr
        if expr is None:
            return set(), set(), False
        return _scan_expr(expr, fn_name_to_keys, enum_map, known_types)
    if isinstance(st, IfStmt):
        c, t, d = _scan_expr(st.cond, fn_name_to_keys, enum_map, known_types)
        for b in st.then_body:
            bc, bt, bd = _scan_stmt(b, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
        for b in st.else_body:
            bc, bt, bd = _scan_stmt(b, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
        return c, t, d
    if isinstance(st, WhileStmt):
        c, t, d = _scan_expr(st.cond, fn_name_to_keys, enum_map, known_types)
        for b in st.body:
            bc, bt, bd = _scan_stmt(b, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
        return c, t, d
    if isinstance(st, ForStmt):
        c: set[str] = set()
        t: set[str] = set()
        d = False
        if st.init is not None:
            if isinstance(st.init, LetStmt):
                bc, bt, bd = _scan_stmt(st.init, fn_name_to_keys, enum_map, known_types)
            else:
                bc, bt, bd = _scan_expr(st.init, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
        if st.cond is not None:
            bc, bt, bd = _scan_expr(st.cond, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
        if st.step is not None:
            if isinstance(st.step, AssignStmt):
                bc, bt, bd = _scan_stmt(st.step, fn_name_to_keys, enum_map, known_types)
            else:
                bc, bt, bd = _scan_expr(st.step, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
        for b in st.body:
            bc, bt, bd = _scan_stmt(b, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
        return c, t, d
    if isinstance(st, MatchStmt):
        c, t, d = _scan_expr(st.expr, fn_name_to_keys, enum_map, known_types)
        for pat, body in st.arms:
            bc, bt, bd = _scan_expr(pat, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
            for b in body:
                bc, bt, bd = _scan_stmt(b, fn_name_to_keys, enum_map, known_types)
                c |= bc
                t |= bt
                d = d or bd
        return c, t, d
    if isinstance(st, (ComptimeStmt, UnsafeStmt)):
        c: set[str] = set()
        t: set[str] = set()
        d = False
        for b in st.body:
            bc, bt, bd = _scan_stmt(b, fn_name_to_keys, enum_map, known_types)
            c |= bc
            t |= bt
            d = d or bd
        return c, t, d
    if isinstance(st, (BreakStmt, ContinueStmt)):
        return set(), set(), False
    return set(), set(), False


def _scan_expr(e: Any, fn_name_to_keys: dict[str, set[str]], enum_map: dict[str, EnumDecl], known_types: set[str]) -> tuple[set[str], set[str], bool]:
    called: set[str] = set()
    used_types: set[str] = set()
    dynamic = False

    if isinstance(e, Name):
        for key in fn_name_to_keys.get(e.value, set()):
            called.add(key)
        return called, used_types, False
    if isinstance(e, Call):
        if isinstance(e.fn, Name):
            resolved = getattr(e, "resolved_name", "") or getattr(e.fn, "resolved_name", "")
            if resolved:
                called.add(resolved)
            else:
                called |= fn_name_to_keys.get(e.fn.value, set())
        elif isinstance(e.fn, FieldExpr) and isinstance(e.fn.obj, Name):
            # Enum constructor call like `Result.Ok(...)`.
            en = enum_map.get(e.fn.obj.value)
            if en is None or not any(v == e.fn.field and payload for v, payload in en.variants):
                dynamic = True
        else:
            dynamic = True
        c, t, d = _scan_expr(e.fn, fn_name_to_keys, enum_map, known_types)
        called |= c
        used_types |= t
        dynamic = dynamic or d
        for arg in e.args:
            c, t, d = _scan_expr(arg, fn_name_to_keys, enum_map, known_types)
            called |= c
            used_types |= t
            dynamic = dynamic or d
        return called, used_types, dynamic
    if isinstance(e, FieldExpr):
        c, t, d = _scan_expr(e.obj, fn_name_to_keys, enum_map, known_types)
        return called | c, used_types | t, dynamic or d
    if isinstance(e, IndexExpr):
        c1, t1, d1 = _scan_expr(e.obj, fn_name_to_keys, enum_map, known_types)
        c2, t2, d2 = _scan_expr(e.index, fn_name_to_keys, enum_map, known_types)
        return c1 | c2, t1 | t2, d1 or d2
    if isinstance(e, Unary):
        return _scan_expr(e.expr, fn_name_to_keys, enum_map, known_types)
    if isinstance(e, Binary):
        c1, t1, d1 = _scan_expr(e.left, fn_name_to_keys, enum_map, known_types)
        c2, t2, d2 = _scan_expr(e.right, fn_name_to_keys, enum_map, known_types)
        return c1 | c2, t1 | t2, d1 or d2
    if isinstance(e, ArrayLit):
        c: set[str] = set()
        t: set[str] = set()
        d = False
        for el in e.elements:
            ec, et, ed = _scan_expr(el, fn_name_to_keys, enum_map, known_types)
            c |= ec
            t |= et
            d = d or ed
        return c, t, d
    if isinstance(e, StructLit):
        used_types.add(e.name)
        c: set[str] = set()
        t: set[str] = set()
        d = False
        for _, val in e.fields:
            ec, et, ed = _scan_expr(val, fn_name_to_keys, enum_map, known_types)
            c |= ec
            t |= et
            d = d or ed
        return c, used_types | t, d
    if isinstance(e, AwaitExpr):
        return _scan_expr(e.expr, fn_name_to_keys, enum_map, known_types)
    if isinstance(e, TypeAnnotated):
        used_types |= _extract_known_types(e.type_name, known_types)
        c, t, d = _scan_expr(e.expr, fn_name_to_keys, enum_map, known_types)
        return c, used_types | t, d
    if isinstance(e, CastExpr):
        used_types |= _extract_known_types(e.type_name, known_types)
        c, t, d = _scan_expr(e.expr, fn_name_to_keys, enum_map, known_types)
        return c, used_types | t, d
    if isinstance(e, (SizeOfTypeExpr, AlignOfTypeExpr, BitSizeOfTypeExpr, MaxValTypeExpr, MinValTypeExpr)):
        used_types |= _extract_known_types(e.type_name, known_types)
        return called, used_types, dynamic
    if isinstance(e, (SizeOfValueExpr, AlignOfValueExpr)):
        return _scan_expr(e.expr, fn_name_to_keys, enum_map, known_types)
    return called, used_types, dynamic
