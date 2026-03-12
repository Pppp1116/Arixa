"""Shared compiler-driven tooling helpers for editor integrations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astra.ast import (
    AssignStmt,
    Binary,
    BoolLit,
    BreakStmt,
    Call,
    CastExpr,
    ComptimeStmt,
    ConstDecl,
    ContinueStmt,
    EnumDecl,
    ExprStmt,
    ExternFnDecl,
    FieldExpr,
    FnDecl,
    GuardedPattern,
    IfExpression,
    IfStmt,
    ImportDecl,
    IndexExpr,
    IteratorForStmt,
    LetStmt,
    Literal,
    MapLiteral,
    MatchStmt,
    MethodCall,
    Name,
    NilLit,
    OrPattern,
    ReturnStmt,
    SetLiteral,
    SizeOfTypeExpr,
    SlicePattern,
    StringInterpolation,
    StructDecl,
    StructLit,
    StructLiteral,
    StructPattern,
    TraitDecl,
    TryExpr,
    TuplePattern,
    TypeAliasDecl,
    TypeAnnotated,
    Unary,
    UnsafeStmt,
    VectorLiteral,
    WhileStmt,
    WildcardPattern,
)
from astra.int_types import INT_WIDTH_MAX, INT_WIDTH_MIN
from astra.lexer import KEYWORDS as LEXER_KEYWORDS
from astra.semantic import BUILTIN_DOCS, BUILTIN_SIGS, GPU_API_DOCS
from astra.type_metadata import FLOAT_TYPES, PRIMITIVES


@dataclass(frozen=True)
class ToolingSymbol:
    """Compiler-derived symbol descriptor for editor tooling."""

    key: str
    name: str
    kind: int
    line: int
    col: int
    detail: str
    uri: str
    doc: str = ""


@dataclass(frozen=True)
class SymbolOccurrence:
    """One symbol occurrence (declaration or reference) in source text."""

    symbol_key: str
    name: str
    line0: int
    col0: int
    length: int
    role: str
    kind: str

    def contains(self, line0: int, col0: int) -> bool:
        if self.line0 != line0:
            return False
        return self.col0 <= col0 < self.col0 + max(1, self.length)

    def to_location(self, uri: str) -> dict[str, Any]:
        return {
            "uri": uri,
            "range": {
                "start": {"line": self.line0, "character": self.col0},
                "end": {"line": self.line0, "character": self.col0 + max(1, self.length)},
            },
        }


@dataclass
class DocumentSemanticIndex:
    """Per-document semantic index used for references/rename/navigation."""

    uri: str
    occurrences: list[SymbolOccurrence]
    symbols: dict[str, ToolingSymbol]

    def symbol_at(self, line0: int, col0: int) -> SymbolOccurrence | None:
        for occ in self.occurrences:
            if occ.contains(line0, col0):
                return occ
        return None

    def locations_for(self, symbol_key: str, *, include_decl: bool = True) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for occ in self.occurrences:
            if occ.symbol_key != symbol_key:
                continue
            if not include_decl and occ.role == "declaration":
                continue
            out.append(occ.to_location(self.uri))
        return out


def compiler_keywords() -> list[str]:
    return sorted(LEXER_KEYWORDS)


def compiler_builtin_signatures():
    return BUILTIN_SIGS


def compiler_builtin_docs():
    return BUILTIN_DOCS


def compiler_gpu_api_docs():
    return GPU_API_DOCS


def compiler_primitive_types() -> list[str]:
    names = set(str(t) for t in PRIMITIVES)
    names.update(FLOAT_TYPES)
    fixed = {8, 16, 32, 64, 128}
    for bits in sorted(fixed):
        if INT_WIDTH_MIN <= bits <= INT_WIDTH_MAX:
            names.add(f"i{bits}")
            names.add(f"u{bits}")
    return sorted(names)


def compiler_common_int_widths() -> list[int]:
    widths = [8, 16, 32, 64, 128]
    return [w for w in widths if INT_WIDTH_MIN <= w <= INT_WIDTH_MAX]


def decl_symbols_from_program(prog: Any, uri: str) -> list[ToolingSymbol]:
    out: list[ToolingSymbol] = []
    for item in getattr(prog, "items", []):
        if isinstance(item, FnDecl):
            sig = ", ".join(f"{n}: {t}" for n, t in item.params)
            key = _top_key(uri, item.name, item.line, item.col, "fn")
            out.append(
                ToolingSymbol(
                    key=key,
                    name=item.name,
                    kind=12,
                    line=item.line,
                    col=item.col,
                    detail=f"fn {item.name}({sig}) {item.ret}",
                    uri=uri,
                    doc=item.doc,
                )
            )
            for pname, pty in item.params:
                pkey = _local_key(uri, item.name, pname, item.line, item.col, "param")
                out.append(
                    ToolingSymbol(
                        key=pkey,
                        name=pname,
                        kind=13,
                        line=item.line,
                        col=item.col,
                        detail=f"param {pname}: {pty}",
                        uri=uri,
                        doc="",
                    )
                )
        elif isinstance(item, ExternFnDecl):
            sig = ", ".join(f"{n}: {t}" for n, t in item.params)
            key = _top_key(uri, item.name, item.line, item.col, "extern")
            out.append(
                ToolingSymbol(
                    key=key,
                    name=item.name,
                    kind=12,
                    line=item.line,
                    col=item.col,
                    detail=f"extern fn {item.name}({sig}) {item.ret}",
                    uri=uri,
                    doc=item.doc,
                )
            )
        elif isinstance(item, StructDecl):
            skey = _top_key(uri, item.name, item.line, item.col, "struct")
            out.append(
                ToolingSymbol(
                    key=skey,
                    name=item.name,
                    kind=23,
                    line=item.line,
                    col=item.col,
                    detail=f"struct {item.name}",
                    uri=uri,
                    doc=item.doc,
                )
            )
            for fname, fty in item.fields:
                fkey = _member_key(uri, item.name, fname, item.line, item.col, "field")
                out.append(
                    ToolingSymbol(
                        key=fkey,
                        name=fname,
                        kind=8,
                        line=item.line,
                        col=item.col,
                        detail=f"field {fname}: {fty}",
                        uri=uri,
                        doc="",
                    )
                )
        elif isinstance(item, EnumDecl):
            ekey = _top_key(uri, item.name, item.line, item.col, "enum")
            out.append(
                ToolingSymbol(
                    key=ekey,
                    name=item.name,
                    kind=10,
                    line=item.line,
                    col=item.col,
                    detail=f"enum {item.name}",
                    uri=uri,
                    doc=item.doc,
                )
            )
            for vname, payload in item.variants:
                ptxt = ", ".join(payload) if payload else ""
                detail = f"variant {vname}" if not ptxt else f"variant {vname}({ptxt})"
                vkey = _member_key(uri, item.name, vname, item.line, item.col, "variant")
                out.append(
                    ToolingSymbol(
                        key=vkey,
                        name=vname,
                        kind=22,
                        line=item.line,
                        col=item.col,
                        detail=detail,
                        uri=uri,
                        doc="",
                    )
                )
        elif isinstance(item, TypeAliasDecl):
            tkey = _top_key(uri, item.name, item.line, item.col, "type")
            out.append(
                ToolingSymbol(
                    key=tkey,
                    name=item.name,
                    kind=5,
                    line=item.line,
                    col=item.col,
                    detail=f"type {item.name} = {item.target}",
                    uri=uri,
                    doc="",
                )
            )
        elif isinstance(item, ConstDecl):
            ckey = _top_key(uri, item.name, item.line, item.col, "const")
            out.append(
                ToolingSymbol(
                    key=ckey,
                    name=item.name,
                    kind=14,
                    line=item.line,
                    col=item.col,
                    detail=f"const {item.name}",
                    uri=uri,
                    doc=item.doc,
                )
            )
        elif isinstance(item, TraitDecl):
            tkey = _top_key(uri, item.name, item.line, item.col, "trait")
            out.append(
                ToolingSymbol(
                    key=tkey,
                    name=item.name,
                    kind=11,
                    line=item.line,
                    col=item.col,
                    detail=f"trait {item.name}",
                    uri=uri,
                    doc=item.doc,
                )
            )
            for mname, params, ret in item.methods:
                sig = ", ".join(f"{n}: {t}" for n, t in params)
                mkey = _member_key(uri, item.name, mname, item.line, item.col, "trait_method")
                out.append(
                    ToolingSymbol(
                        key=mkey,
                        name=mname,
                        kind=12,
                        line=item.line,
                        col=item.col,
                        detail=f"trait fn {mname}({sig}) {ret}",
                        uri=uri,
                        doc="",
                    )
                )
        elif isinstance(item, ImportDecl):
            if item.alias:
                ikey = _top_key(uri, item.alias, item.line, item.col, "import_alias")
                out.append(
                    ToolingSymbol(
                        key=ikey,
                        name=item.alias,
                        kind=2,
                        line=item.line,
                        col=item.col,
                        detail="import alias",
                        uri=uri,
                        doc="",
                    )
                )
    return out


def decl_map_from_symbols(symbols: list[ToolingSymbol]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols:
        if sym.kind in {8, 22, 13}:
            continue
        out[sym.name] = {
            "line": sym.line,
            "col": sym.col,
            "detail": sym.detail,
            "doc": sym.doc,
            "kind": sym.kind,
            "key": sym.key,
        }
    return out


def build_document_semantic_index(prog: Any, uri: str) -> DocumentSemanticIndex:
    symbols = decl_symbols_from_program(prog, uri)
    symbol_map = {s.key: s for s in symbols}
    top_level: dict[str, str] = {
        s.name: s.key
        for s in symbols
        if s.kind in {2, 5, 10, 11, 12, 14, 23}
    }
    occurrences: list[SymbolOccurrence] = []

    # Declarations.
    for sym in symbols:
        line0 = max(0, int(sym.line) - 1)
        col0 = max(0, int(sym.col) - 1)
        if line0 == 0 and col0 == 0 and not sym.name:
            continue
        occurrences.append(
            SymbolOccurrence(
                symbol_key=sym.key,
                name=sym.name,
                line0=line0,
                col0=col0,
                length=max(1, len(sym.name)),
                role="declaration",
                kind=_kind_name(sym.kind),
            )
        )

    for item in getattr(prog, "items", []):
        if isinstance(item, FnDecl):
            _index_fn_body(item, uri, top_level, symbol_map, occurrences)

    return DocumentSemanticIndex(uri=uri, occurrences=occurrences, symbols=symbol_map)


def _kind_name(kind: int) -> str:
    mapping = {
        2: "module",
        5: "type",
        6: "variable",
        8: "field",
        10: "enum",
        11: "trait",
        12: "function",
        13: "parameter",
        14: "constant",
        22: "enum_member",
        23: "struct",
    }
    return mapping.get(kind, "symbol")


def _top_key(uri: str, name: str, line: int, col: int, kind: str) -> str:
    return f"top:{uri}:{kind}:{name}:{line}:{col}"


def _member_key(uri: str, owner: str, name: str, line: int, col: int, kind: str) -> str:
    return f"member:{uri}:{owner}:{kind}:{name}:{line}:{col}"


def _local_key(uri: str, fn_name: str, name: str, line: int, col: int, kind: str) -> str:
    return f"local:{uri}:{fn_name}:{kind}:{name}:{line}:{col}"


def _index_fn_body(
    fn: FnDecl,
    uri: str,
    top_level: dict[str, str],
    symbol_map: dict[str, ToolingSymbol],
    occurrences: list[SymbolOccurrence],
) -> None:
    scopes: list[dict[str, str]] = [{}]
    param_map: dict[str, str] = {}
    for pname, pty in fn.params:
        pkey = _local_key(uri, fn.name, pname, fn.line, fn.col, "param")
        param_map[pname] = pkey
        scopes[-1][pname] = pkey
        symbol_map.setdefault(
            pkey,
            ToolingSymbol(
                key=pkey,
                name=pname,
                kind=13,
                line=fn.line,
                col=fn.col,
                detail=f"param {pname}: {pty}",
                uri=uri,
                doc="",
            ),
        )
    _walk_stmts(fn.body, uri, fn.name, scopes, top_level, symbol_map, occurrences)


def _walk_stmts(
    stmts: list[Any],
    uri: str,
    fn_name: str,
    scopes: list[dict[str, str]],
    top_level: dict[str, str],
    symbol_map: dict[str, ToolingSymbol],
    occurrences: list[SymbolOccurrence],
) -> None:
    for st in stmts:
        if isinstance(st, LetStmt):
            _walk_expr(st.expr, uri, scopes, top_level, occurrences)
            lkey = _local_key(uri, fn_name, st.name, st.line, st.col, "local")
            scopes[-1][st.name] = lkey
            symbol_map.setdefault(
                lkey,
                ToolingSymbol(
                    key=lkey,
                    name=st.name,
                    kind=6,
                    line=st.line,
                    col=st.col,
                    detail=f"let {st.name}" if st.type_name is None else f"let {st.name}: {st.type_name}",
                    uri=uri,
                    doc="",
                ),
            )
            occurrences.append(
                SymbolOccurrence(
                    symbol_key=lkey,
                    name=st.name,
                    line0=max(0, st.line - 1),
                    col0=max(0, st.col - 1),
                    length=max(1, len(st.name)),
                    role="declaration",
                    kind="variable",
                )
            )
            continue
        if isinstance(st, AssignStmt):
            _walk_expr(st.target, uri, scopes, top_level, occurrences)
            _walk_expr(st.expr, uri, scopes, top_level, occurrences)
            continue
        if isinstance(st, ExprStmt):
            _walk_expr(st.expr, uri, scopes, top_level, occurrences)
            continue
        if isinstance(st, ReturnStmt):
            if st.expr is not None:
                _walk_expr(st.expr, uri, scopes, top_level, occurrences)
            continue
        if isinstance(st, IteratorForStmt):
            _walk_expr(st.iterable, uri, scopes, top_level, occurrences)
            scopes.append({})
            vkey = _local_key(uri, fn_name, st.var_name, st.line, st.col, "loop_var")
            scopes[-1][st.var_name] = vkey
            symbol_map.setdefault(
                vkey,
                ToolingSymbol(
                    key=vkey,
                    name=st.var_name,
                    kind=6,
                    line=st.line,
                    col=st.col,
                    detail=f"for {st.var_name}",
                    uri=uri,
                    doc="",
                ),
            )
            occurrences.append(
                SymbolOccurrence(
                    symbol_key=vkey,
                    name=st.var_name,
                    line0=max(0, st.line - 1),
                    col0=max(0, st.col - 1),
                    length=max(1, len(st.var_name)),
                    role="declaration",
                    kind="variable",
                )
            )
            _walk_stmts(st.body, uri, fn_name, scopes, top_level, symbol_map, occurrences)
            scopes.pop()
            continue
        if isinstance(st, IfStmt):
            _walk_expr(st.cond, uri, scopes, top_level, occurrences)
            scopes.append({})
            _walk_stmts(st.then_body, uri, fn_name, scopes, top_level, symbol_map, occurrences)
            scopes.pop()
            scopes.append({})
            _walk_stmts(st.else_body, uri, fn_name, scopes, top_level, symbol_map, occurrences)
            scopes.pop()
            continue
        if isinstance(st, WhileStmt):
            _walk_expr(st.cond, uri, scopes, top_level, occurrences)
            scopes.append({})
            _walk_stmts(st.body, uri, fn_name, scopes, top_level, symbol_map, occurrences)
            scopes.pop()
            continue
        if isinstance(st, MatchStmt):
            _walk_expr(st.expr, uri, scopes, top_level, occurrences)
            for pat, arm_body in st.arms:
                scopes.append({})
                _declare_pattern_binds(pat, uri, fn_name, scopes, symbol_map, occurrences)
                _walk_stmts(arm_body, uri, fn_name, scopes, top_level, symbol_map, occurrences)
                scopes.pop()
            continue
        if isinstance(st, ComptimeStmt):
            scopes.append({})
            _walk_stmts(st.body, uri, fn_name, scopes, top_level, symbol_map, occurrences)
            scopes.pop()
            continue
        if isinstance(st, UnsafeStmt):
            scopes.append({})
            _walk_stmts(st.body, uri, fn_name, scopes, top_level, symbol_map, occurrences)
            scopes.pop()
            continue
        if isinstance(st, (BreakStmt, ContinueStmt)):
            continue


def _declare_pattern_binds(
    pat: Any,
    uri: str,
    fn_name: str,
    scopes: list[dict[str, str]],
    symbol_map: dict[str, ToolingSymbol],
    occurrences: list[SymbolOccurrence],
) -> None:
    if isinstance(pat, WildcardPattern):
        return
    if isinstance(pat, Name):
        if pat.value == "_":
            return
        key = _local_key(uri, fn_name, pat.value, pat.line, pat.col, "pattern_bind")
        scopes[-1][pat.value] = key
        symbol_map.setdefault(
            key,
            ToolingSymbol(
                key=key,
                name=pat.value,
                kind=6,
                line=pat.line,
                col=pat.col,
                detail=f"pattern {pat.value}",
                uri=uri,
                doc="",
            ),
        )
        occurrences.append(
            SymbolOccurrence(
                symbol_key=key,
                name=pat.value,
                line0=max(0, pat.line - 1),
                col0=max(0, pat.col - 1),
                length=max(1, len(pat.value)),
                role="declaration",
                kind="variable",
            )
        )
        return
    if isinstance(pat, GuardedPattern):
        _declare_pattern_binds(pat.pattern, uri, fn_name, scopes, symbol_map, occurrences)
        return
    if isinstance(pat, OrPattern):
        for sub in pat.patterns:
            _declare_pattern_binds(sub, uri, fn_name, scopes, symbol_map, occurrences)
        return
    if isinstance(pat, StructPattern):
        for sub in pat.field_patterns.values():
            _declare_pattern_binds(sub, uri, fn_name, scopes, symbol_map, occurrences)
        return
    if isinstance(pat, TuplePattern):
        for sub in pat.patterns:
            _declare_pattern_binds(sub, uri, fn_name, scopes, symbol_map, occurrences)
        return
    if isinstance(pat, SlicePattern):
        for sub in pat.patterns:
            _declare_pattern_binds(sub, uri, fn_name, scopes, symbol_map, occurrences)
        if pat.rest_pattern is not None:
            _declare_pattern_binds(pat.rest_pattern, uri, fn_name, scopes, symbol_map, occurrences)
        return


def _resolve_name(
    name: str,
    scopes: list[dict[str, str]],
    top_level: dict[str, str],
) -> str | None:
    for scope in reversed(scopes):
        hit = scope.get(name)
        if hit is not None:
            return hit
    if name in top_level:
        return top_level[name]
    if name in BUILTIN_SIGS:
        return f"builtin::{name}"
    return None


def _walk_expr(
    expr: Any,
    uri: str,
    scopes: list[dict[str, str]],
    top_level: dict[str, str],
    occurrences: list[SymbolOccurrence],
) -> None:
    if expr is None:
        return
    if isinstance(expr, Name):
        key = _resolve_name(expr.value, scopes, top_level)
        if key is not None:
            occurrences.append(
                SymbolOccurrence(
                    symbol_key=key,
                    name=expr.value,
                    line0=max(0, expr.line - 1),
                    col0=max(0, expr.col - 1),
                    length=max(1, len(expr.value)),
                    role="reference",
                    kind="name",
                )
            )
        return
    if isinstance(expr, Literal | BoolLit | NilLit | SizeOfTypeExpr):
        return
    if isinstance(expr, Call):
        _walk_expr(expr.fn, uri, scopes, top_level, occurrences)
        for arg in expr.args:
            _walk_expr(arg, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, MethodCall):
        _walk_expr(expr.obj, uri, scopes, top_level, occurrences)
        for arg in expr.args:
            _walk_expr(arg, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, FieldExpr):
        _walk_expr(expr.obj, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, Binary):
        _walk_expr(expr.left, uri, scopes, top_level, occurrences)
        _walk_expr(expr.right, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, Unary):
        _walk_expr(expr.expr, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, IndexExpr):
        _walk_expr(expr.obj, uri, scopes, top_level, occurrences)
        _walk_expr(expr.index, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, StringInterpolation):
        for sub in expr.exprs:
            _walk_expr(sub, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, StructLiteral):
        for arg in expr.args:
            _walk_expr(arg, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, StructLit):
        for _, sub in expr.fields:
            _walk_expr(sub, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, VectorLiteral):
        for sub in expr.elements:
            _walk_expr(sub, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, MapLiteral):
        for k, v in expr.pairs:
            _walk_expr(k, uri, scopes, top_level, occurrences)
            _walk_expr(v, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, SetLiteral):
        for sub in expr.elements:
            _walk_expr(sub, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, TypeAnnotated):
        _walk_expr(expr.expr, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, CastExpr):
        _walk_expr(expr.expr, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, IfExpression):
        _walk_expr(expr.cond, uri, scopes, top_level, occurrences)
        _walk_expr(expr.then_expr, uri, scopes, top_level, occurrences)
        _walk_expr(expr.else_expr, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, TryExpr):
        _walk_expr(expr.expr, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, tuple):
        for sub in expr:
            _walk_expr(sub, uri, scopes, top_level, occurrences)
        return
    if isinstance(expr, list):
        for sub in expr:
            _walk_expr(sub, uri, scopes, top_level, occurrences)
