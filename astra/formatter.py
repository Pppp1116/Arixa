"""Source formatter and config resolution for Astra files."""

import argparse
import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

from astra.ast import *
from astra.parser import BIN_PREC as PARSER_BIN_PREC
from astra.parser import ParseError, parse


# Keep expression precedence aligned with parser behavior.
FMT_BIN_PREC = dict(PARSER_BIN_PREC)
_MAX_BIN_PREC = max(FMT_BIN_PREC.values(), default=1)
_PREC_CAST = _MAX_BIN_PREC + 1
_PREC_UNARY = _MAX_BIN_PREC + 2
_PREC_POSTFIX = _MAX_BIN_PREC + 3
_PREC_ATOM = _MAX_BIN_PREC + 4


@dataclass(frozen=True)
class FormatConfig:
    """Data container used by formatter.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    indent_width: int = 4
    line_width: int = 100


def _safe_int(v) -> int | None:
    try:
        return int(v)
    except Exception:
        return None


def _extract_cfg_from_toml(data: dict, default: FormatConfig) -> FormatConfig:
    indent = default.indent_width
    width = default.line_width

    def pick(src: dict | None) -> None:
        nonlocal indent, width
        if not isinstance(src, dict):
            return
        iw = _safe_int(src.get("indent_width"))
        if iw in {2, 4, 8}:
            indent = iw
        lw = _safe_int(src.get("line_width"))
        if lw and lw >= 40:
            width = lw

    pick(data)
    pick(data.get("format"))
    pick(data.get("astfmt"))
    pick(data.get("formatter"))
    return FormatConfig(indent_width=indent, line_width=width)


def resolve_format_config(for_path: Path | None = None) -> FormatConfig:
    """Resolve and return data for `resolve_format_config`.
    
    Parameters:
        for_path: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    cfg = FormatConfig()
    start = (for_path.resolve().parent if for_path else Path.cwd().resolve())
    for cur in (start, *start.parents):
        astfmt = cur / "astfmt.toml"
        if astfmt.exists():
            try:
                return _extract_cfg_from_toml(tomllib.loads(astfmt.read_text()), cfg)
            except Exception:
                return cfg
        manifest = cur / "Astra.toml"
        if manifest.exists():
            try:
                return _extract_cfg_from_toml(tomllib.loads(manifest.read_text()), cfg)
            except Exception:
                return cfg
    return cfg


def _indent(ind: int, cfg: FormatConfig) -> str:
    return " " * (cfg.indent_width * ind)


def _expr_prec(e) -> int:
    if isinstance(e, Binary):
        return FMT_BIN_PREC[e.op]
    if isinstance(e, CastExpr):
        return _PREC_CAST
    if isinstance(e, (AwaitExpr, Unary)):
        return _PREC_UNARY
    if isinstance(e, (Call, IndexExpr, FieldExpr, TryExpr)):
        return _PREC_POSTFIX
    return _PREC_ATOM


def _fmt_expr_with_prec(e, cfg: FormatConfig, parent_prec: int = 0, right_child: bool = False) -> str:
    text = _fmt_expr(e, cfg)
    my_prec = _expr_prec(e)
    if my_prec < parent_prec:
        return f"({text})"
    if isinstance(e, Binary) and right_child and my_prec == parent_prec:
        # Parser makes binary operators left-associative; keep right-nested groups explicit.
        return f"({text})"
    return text


def _wrap_call_like(head: str, args: list[str], cfg: FormatConfig, *, indent: int) -> str:
    inline = f"{head}({', '.join(args)})"
    if len(inline) <= cfg.line_width or not args:
        return inline
    p = _indent(indent, cfg)
    p1 = _indent(indent + 1, cfg)
    body = ",\n".join(f"{p1}{a}" for a in args)
    return f"{head}(\n{body}\n{p})"


def _fmt_expr(e, cfg: FormatConfig, *, indent: int = 0) -> str:
    if isinstance(e, BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, NilLit):
        return "none"
    if isinstance(e, Literal):
        if isinstance(e.value, str):
            return json.dumps(e.value)
        return str(e.value)
    if isinstance(e, Name):
        return e.value
    if isinstance(e, WildcardPattern):
        return "_"
    if isinstance(e, OrPattern):
        return " | ".join(_fmt_expr(p, cfg, indent=indent) for p in e.patterns)
    if isinstance(e, GuardedPattern):
        return f"{_fmt_expr(e.pattern, cfg, indent=indent)} if {_fmt_expr(e.guard, cfg, indent=indent)}"
    if isinstance(e, AwaitExpr):
        return f"await {_fmt_expr_with_prec(e.expr, cfg, _PREC_UNARY)}"
    if isinstance(e, TryExpr):
        return f"{_fmt_expr_with_prec(e.expr, cfg, _PREC_POSTFIX)}!"
    if isinstance(e, Unary):
        return f"{e.op}{_fmt_expr_with_prec(e.expr, cfg, _PREC_UNARY)}"
    if isinstance(e, CastExpr):
        return f"{_fmt_expr_with_prec(e.expr, cfg, _PREC_CAST)} as {type_text(e.type_name)}"
    if isinstance(e, TypeAnnotated):
        return f"{_fmt_expr_with_prec(e.expr, cfg, _PREC_CAST)} as {type_text(e.type_name)}"
    if isinstance(e, Binary):
        p = FMT_BIN_PREC[e.op]
        left = _fmt_expr_with_prec(e.left, cfg, p, right_child=False)
        right = _fmt_expr_with_prec(e.right, cfg, p, right_child=True)
        return f"{left} {e.op} {right}"
    if isinstance(e, Call):
        fn = _fmt_expr_with_prec(e.fn, cfg, _PREC_POSTFIX)
        args = [_fmt_expr(a, cfg, indent=indent + 1) for a in e.args]
        return _wrap_call_like(fn, args, cfg, indent=indent)
    if isinstance(e, IndexExpr):
        obj = _fmt_expr_with_prec(e.obj, cfg, _PREC_POSTFIX)
        return f"{obj}[{_fmt_expr(e.index, cfg, indent=indent)}]"
    if isinstance(e, FieldExpr):
        obj = _fmt_expr_with_prec(e.obj, cfg, _PREC_POSTFIX)
        return f"{obj}.{e.field}"
    if isinstance(e, ArrayLit):
        vals = [_fmt_expr(x, cfg, indent=indent + 1) for x in e.elements]
        return _wrap_call_like("", vals, cfg, indent=indent).replace("(", "[", 1).rsplit(")", 1)[0] + "]"
    if isinstance(e, VectorLiteral):
        vals = [_fmt_expr(x, cfg, indent=indent + 1) for x in e.elements]
        return _wrap_call_like("vec", vals, cfg, indent=indent)
    if isinstance(e, MapLiteral):
        vals = []
        for k, v in e.pairs:
            vals.append(f"{_fmt_expr(k, cfg, indent=indent + 1)}: {_fmt_expr(v, cfg, indent=indent + 1)}")
        return _wrap_call_like("", vals, cfg, indent=indent).replace("(", "{", 1).rsplit(")", 1)[0] + "}"
    if isinstance(e, SetLiteral):
        vals = [_fmt_expr(x, cfg, indent=indent + 1) for x in e.elements]
        return _wrap_call_like("", vals, cfg, indent=indent).replace("(", "{", 1).rsplit(")", 1)[0] + "}"
    if isinstance(e, IfExpression):
        cond = _fmt_expr(e.cond, cfg, indent=indent + 1)
        then_expr = _fmt_expr(e.then_expr, cfg, indent=indent + 1)
        else_expr = _fmt_expr(e.else_expr, cfg, indent=indent + 1)
        return f"if {cond} {{ {then_expr} }} else {{ {else_expr} }}"
    if isinstance(e, StructLit):
        vals = [_fmt_expr(v, cfg, indent=indent + 1) for _, v in e.fields]
        return _wrap_call_like(e.name, vals, cfg, indent=indent)
    if isinstance(e, RangeExpr):
        dots = "..=" if e.inclusive else ".."
        return f"{_fmt_expr(e.start, cfg, indent=indent)}{dots}{_fmt_expr(e.end, cfg, indent=indent)}"
    if isinstance(e, SizeOfTypeExpr):
        return f"sizeof({type_text(e.type_name)})"
    if isinstance(e, AlignOfTypeExpr):
        return f"alignof({type_text(e.type_name)})"
    if isinstance(e, BitSizeOfTypeExpr):
        return f"bitSizeOf({type_text(e.type_name)})"
    if isinstance(e, MaxValTypeExpr):
        return f"maxVal({type_text(e.type_name)})"
    if isinstance(e, MinValTypeExpr):
        return f"minVal({type_text(e.type_name)})"
    if isinstance(e, SizeOfValueExpr):
        return f"size_of({_fmt_expr(e.expr, cfg, indent=indent)})"
    if isinstance(e, AlignOfValueExpr):
        return f"align_of({_fmt_expr(e.expr, cfg, indent=indent)})"
    if isinstance(e, MethodCall):
        obj = _fmt_expr_with_prec(e.obj, cfg, _PREC_POSTFIX)
        args = [_fmt_expr(a, cfg, indent=indent + 1) for a in e.args]
        return _wrap_call_like(f"{obj}.{e.method}", args, cfg, indent=indent)
    raise ValueError(f"formatter: unsupported expression node {type(e).__name__}")


def _fmt_match_pattern(pat, cfg: FormatConfig, *, indent: int = 0) -> str:
    return _fmt_expr(pat, cfg, indent=indent)


def _fmt_block(prefix: str, body: list, ind: int, cfg: FormatConfig) -> list[str]:
    p = _indent(ind, cfg)
    if not body:
        return [f"{p}{prefix} {{}}"]
    out = [f"{p}{prefix} {{"]
    for s in body:
        out.extend(_fmt_stmt(s, ind + 1, cfg))
    out.append(f"{p}}}")
    return out


def _fmt_stmt(st, ind: int, cfg: FormatConfig) -> list[str]:
    p = _indent(ind, cfg)
    if isinstance(st, LetStmt):
        mut = "mut " if st.mut else ""
        ann = f": {type_text(st.type_name)}" if st.type_name else ""
        return [f"{p}{mut}{st.name}{ann} = {_fmt_expr(st.expr, cfg, indent=ind)};"]
    if isinstance(st, AssignStmt):
        set_kw = "set " if getattr(st, "explicit_set", False) else ""
        return [f"{p}{set_kw}{_fmt_expr(st.target, cfg, indent=ind)} {st.op} {_fmt_expr(st.expr, cfg, indent=ind)};"]
    if isinstance(st, ReturnStmt):
        if st.expr is None:
            return [f"{p}return;"]
        return [f"{p}return {_fmt_expr(st.expr, cfg, indent=ind)};"]
    if isinstance(st, BreakStmt):
        return [f"{p}break;"]
    if isinstance(st, ContinueStmt):
        return [f"{p}continue;"]
    if isinstance(st, ExprStmt):
        return [f"{p}{_fmt_expr(st.expr, cfg, indent=ind)};"]
    if isinstance(st, UnsafeStmt):
        return _fmt_block("unsafe", st.body, ind, cfg)
    if isinstance(st, ComptimeStmt):
        return _fmt_block("comptime", st.body, ind, cfg)
    if isinstance(st, IfStmt):
        out = _fmt_block(f"if {_fmt_expr(st.cond, cfg, indent=ind)}", st.then_body, ind, cfg)
        if st.else_body is not None:
            out.extend(_fmt_block("else", st.else_body, ind, cfg))
        return out
    if isinstance(st, WhileStmt):
        return _fmt_block(f"while {_fmt_expr(st.cond, cfg, indent=ind)}", st.body, ind, cfg)
    if isinstance(st, ForStmt):
        return _fmt_block(f"for {st.var} in {_fmt_expr(st.iterable, cfg, indent=ind)}", st.body, ind, cfg)
    if isinstance(st, MatchStmt):
        out = [f"{p}match {_fmt_expr(st.expr, cfg, indent=ind)} {{"]
        for pat, body in st.arms:
            head = f"{_indent(ind + 1, cfg)}{_fmt_match_pattern(pat, cfg, indent=ind + 1)} =>"
            if not body:
                out.append(f"{head} {{}}")
                continue
            out.append(f"{head} {{")
            for s in body:
                out.extend(_fmt_stmt(s, ind + 2, cfg))
            out.append(f"{_indent(ind + 1, cfg)}}}")
        out.append(f"{p}}}")
        return out
    raise ValueError(f"formatter: unsupported statement node {type(st).__name__}")


def _fmt_item(item, cfg: FormatConfig) -> list[str]:
    def _fmt_generics(generics: list[str], where_bounds: list[tuple[str, str]] | None = None) -> str:
        if not generics:
            return ""
        grouped: dict[str, list[str]] = {}
        for tv, tr in list(where_bounds or []):
            grouped.setdefault(tv, []).append(tr)
        parts: list[str] = []
        for g in generics:
            bounds = grouped.get(g, [])
            if bounds:
                parts.append(f"{g} {' + '.join(bounds)}")
            else:
                parts.append(g)
        return f"<{', '.join(parts)}>"

    if isinstance(item, ImportDecl):
        alias = f" as {item.alias}" if item.alias else ""
        if item.source is not None:
            return [f'import "{item.source}"{alias};']
        return [f"import {'.'.join(item.path)}{alias};"]
    if isinstance(item, TypeAliasDecl):
        return [f"type {item.name} = {type_text(item.target)};"]
    if isinstance(item, LetStmt):
        mut = "mut " if item.mut else ""
        ann = f": {type_text(item.type_name)}" if item.type_name else ""
        return [f"{mut}{item.name}{ann} = {_fmt_expr(item.expr, cfg)};"]
    if isinstance(item, ConstDecl):
        return [f"const {item.name} = {_fmt_expr(item.expr, cfg)};"]
    if isinstance(item, StructDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        if getattr(item, "derives", None):
            out.append(f"@derive({', '.join(getattr(item, 'derives'))})")
        pub = "pub " if item.pub else ""
        packed = "@packed " if item.packed else ""
        gen = _fmt_generics(item.generics)
        if not item.fields:
            out.append(f"{pub}{packed}struct {item.name}{gen} {{}}")
            return out
        out.append(f"{pub}{packed}struct {item.name}{gen} {{")
        for name, typ in item.fields:
            out.append(f"{_indent(1, cfg)}{name} {type_text(typ)},")
        out.append("}")
        return out
    if isinstance(item, EnumDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        if getattr(item, "derives", None):
            out.append(f"@derive({', '.join(getattr(item, 'derives'))})")
        pub = "pub " if item.pub else ""
        gen = _fmt_generics(item.generics)
        if not item.variants:
            out.append(f"{pub}enum {item.name}{gen} {{}}")
            return out
        out.append(f"{pub}enum {item.name}{gen} {{")
        for name, fields in item.variants:
            if fields:
                out.append(f"{_indent(1, cfg)}{name}({', '.join(type_text(t) for t in fields)}),")
            else:
                out.append(f"{_indent(1, cfg)}{name},")
        out.append("}")
        return out
    if isinstance(item, ExternFnDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        pub = "pub " if item.pub else ""
        us = "unsafe " if item.unsafe else ""
        libs = list(item.link_libs) or ([item.lib] if item.lib else [])
        for lib in libs:
            out.append(f'@link("{lib}")')
        sig_parts = [f"{n} {type_text(t)}" for n, t in item.params]
        if item.is_variadic:
            sig_parts.append("...")
        sig = ", ".join(sig_parts)
        ret_text = f" {type_text(item.ret)}" if type_text(item.ret) != "Void" else ""
        line = f"{pub}{us}extern fn {item.name}({sig}){ret_text};"
        if len(line) <= cfg.line_width or not item.params:
            out.append(line)
            return out
        out.append(f"{pub}{us}extern fn {item.name}(")
        for n, t in item.params:
            out.append(f"{_indent(1, cfg)}{n} {type_text(t)},")
        if item.is_variadic:
            out.append(f"{_indent(1, cfg)}...,")
        ret_text = f" {type_text(item.ret)}" if type_text(item.ret) != "Void" else ""
        out.append(f"){ret_text};")
        return out
    if isinstance(item, FnDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        pub = "pub " if item.pub else ""
        async_kw = "async " if item.async_fn else ""
        unsafe_kw = "unsafe " if item.unsafe else ""
        gpu_kw = "gpu " if getattr(item, "gpu_kernel", False) else ""
        gen = _fmt_generics(item.generics, item.where_bounds)
        sig = ", ".join(f"{n} {type_text(t)}" for n, t in item.params)
        ret_text = f" {type_text(item.ret)}" if type_text(item.ret) != "Void" else ""
        fn_head = f"{pub}{async_kw}{unsafe_kw}{gpu_kw}fn {item.name}{gen}({sig}){ret_text}"
        if len(fn_head) > cfg.line_width and item.params:
            out.append(f"{pub}{async_kw}{unsafe_kw}{gpu_kw}fn {item.name}{gen}(")
            for n, t in item.params:
                out.append(f"{_indent(1, cfg)}{n} {type_text(t)},")
            fn_head = f"){ret_text}"
        if not item.body:
            out.append(f"{fn_head} {{}}")
            return out
        out.append(f"{fn_head} {{")
        for st in item.body:
            out.extend(_fmt_stmt(st, 1, cfg))
        out.append("}")
        return out
    if isinstance(item, TraitDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        pub = "pub " if item.pub else ""
        out.append(f"{pub}trait {item.name} {{")
        for mname, params, ret in item.methods:
            sig = ", ".join(f"{n} {type_text(t)}" for n, t in params)
            ret_text = f" {type_text(ret)}" if type_text(ret) != "Void" else ""
            out.append(f"{_indent(1, cfg)}fn {mname}({sig}){ret_text};")
        out.append("}")
        return out
    raise ValueError(f"formatter: unsupported top-level node {type(item).__name__}")


def fmt(src: str, *, config: FormatConfig | None = None) -> str:
    """Format Astra source text according to formatter configuration.
    
    Parameters:
        src: Astra source text to process.
        config: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    cfg = config or FormatConfig()
    try:
        prog = parse(src)
    except ParseError:
        out = []
        indent = 0
        for raw in src.splitlines():
            line = raw.strip()
            if line.startswith("}"):
                indent = max(0, indent - 1)
            out.append((" " * (cfg.indent_width * indent)) + line)
            if line.endswith("{"):
                indent += 1
        return "\n".join(out) + "\n"
    out: list[str] = []
    for item in prog.items:
        out.extend(_fmt_item(item, cfg))
        out.append("")
    if out:
        out.pop()
    return "\n".join(out) + "\n"


def main(argv=None):
    """CLI-style entrypoint for this module.
    
    Parameters:
        argv: Optional CLI arguments passed instead of process argv.
    
    Returns:
        Value produced by the routine, if any.
    """
    p = argparse.ArgumentParser()
    p.add_argument("file")
    ns = p.parse_args(argv)
    f = Path(ns.file)
    cfg = resolve_format_config(f)
    f.write_text(fmt(f.read_text(), config=cfg))
    print("formatted")


if __name__ == "__main__":
    main()
