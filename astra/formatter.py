import argparse
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


def _expr_prec(e) -> int:
    if isinstance(e, Binary):
        return FMT_BIN_PREC[e.op]
    if isinstance(e, CastExpr):
        return _PREC_CAST
    if isinstance(e, (AwaitExpr, Unary)):
        return _PREC_UNARY
    if isinstance(e, (Call, IndexExpr, FieldExpr)):
        return _PREC_POSTFIX
    return _PREC_ATOM


def _fmt_expr_with_prec(e, parent_prec: int = 0, right_child: bool = False) -> str:
    text = _fmt_expr(e)
    my_prec = _expr_prec(e)
    if my_prec < parent_prec:
        return f"({text})"
    if isinstance(e, Binary) and right_child and my_prec == parent_prec:
        # Parser makes binary operators left-associative; keep right-nested groups explicit.
        return f"({text})"
    return text


def _fmt_expr(e) -> str:
    if isinstance(e, BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, NilLit):
        return "none"
    if isinstance(e, Literal):
        if isinstance(e.value, str):
            return repr(e.value).replace("'", '"')
        return str(e.value)
    if isinstance(e, Name):
        return e.value
    if isinstance(e, AwaitExpr):
        return f"await {_fmt_expr_with_prec(e.expr, _PREC_UNARY)}"
    if isinstance(e, Unary):
        return f"{e.op}{_fmt_expr_with_prec(e.expr, _PREC_UNARY)}"
    if isinstance(e, CastExpr):
        return f"{_fmt_expr_with_prec(e.expr, _PREC_CAST)} as {e.type_name}"
    if isinstance(e, Binary):
        p = FMT_BIN_PREC[e.op]
        left = _fmt_expr_with_prec(e.left, p, right_child=False)
        right = _fmt_expr_with_prec(e.right, p, right_child=True)
        return f"{left} {e.op} {right}"
    if isinstance(e, Call):
        fn = _fmt_expr_with_prec(e.fn, _PREC_POSTFIX)
        return f"{fn}({', '.join(_fmt_expr(a) for a in e.args)})"
    if isinstance(e, IndexExpr):
        obj = _fmt_expr_with_prec(e.obj, _PREC_POSTFIX)
        return f"{obj}[{_fmt_expr(e.index)}]"
    if isinstance(e, FieldExpr):
        obj = _fmt_expr_with_prec(e.obj, _PREC_POSTFIX)
        return f"{obj}.{e.field}"
    if isinstance(e, ArrayLit):
        return f"[{', '.join(_fmt_expr(x) for x in e.elements)}]"
    if isinstance(e, SizeOfTypeExpr):
        return f"sizeof({e.type_name})"
    if isinstance(e, AlignOfTypeExpr):
        return f"alignof({e.type_name})"
    if isinstance(e, SizeOfValueExpr):
        return f"size_of({_fmt_expr(e.expr)})"
    if isinstance(e, AlignOfValueExpr):
        return f"align_of({_fmt_expr(e.expr)})"
    return "/* unsupported */"


def _fmt_stmt(st, ind: int) -> list[str]:
    p = "    " * ind
    if isinstance(st, LetStmt):
        kw = "fixed" if st.fixed else "let"
        mut = "mut " if st.mut and not st.fixed else ""
        ann = f": {st.type_name}" if st.type_name else ""
        return [f"{p}{kw} {mut}{st.name}{ann} = {_fmt_expr(st.expr)};"]
    if isinstance(st, AssignStmt):
        return [f"{p}{_fmt_expr(st.target)} {st.op} {_fmt_expr(st.expr)};"]
    if isinstance(st, ReturnStmt):
        if st.expr is None:
            return [f"{p}return;"]
        return [f"{p}return {_fmt_expr(st.expr)};"]
    if isinstance(st, BreakStmt):
        return [f"{p}break;"]
    if isinstance(st, ContinueStmt):
        return [f"{p}continue;"]
    if isinstance(st, ExprStmt):
        return [f"{p}{_fmt_expr(st.expr)};"]
    if isinstance(st, DropStmt):
        return [f"{p}drop {_fmt_expr(st.expr)};"]
    if isinstance(st, IfStmt):
        out = [f"{p}if {_fmt_expr(st.cond)} {{"]
        for s in st.then_body:
            out.extend(_fmt_stmt(s, ind + 1))
        out.append(f"{p}}}")
        if st.else_body:
            out[-1] += " else {"
            for s in st.else_body:
                out.extend(_fmt_stmt(s, ind + 1))
            out.append(f"{p}}}")
        return out
    if isinstance(st, WhileStmt):
        out = [f"{p}while {_fmt_expr(st.cond)} {{"]
        for s in st.body:
            out.extend(_fmt_stmt(s, ind + 1))
        out.append(f"{p}}}")
        return out
    if isinstance(st, ForStmt):
        init = ""
        if isinstance(st.init, LetStmt):
            init_kw = "fixed" if st.init.fixed else "let"
            init_mut = "mut " if st.init.mut and not st.init.fixed else ""
            init = f"{init_kw} {init_mut}{st.init.name} = {_fmt_expr(st.init.expr)}"
        elif st.init is not None:
            init = _fmt_expr(st.init)
        cond = _fmt_expr(st.cond) if st.cond is not None else ""
        if isinstance(st.step, AssignStmt):
            step = f"{_fmt_expr(st.step.target)} {st.step.op} {_fmt_expr(st.step.expr)}"
        else:
            step = _fmt_expr(st.step) if st.step is not None else ""
        out = [f"{p}for {init}; {cond}; {step} {{"]
        for s in st.body:
            out.extend(_fmt_stmt(s, ind + 1))
        out.append(f"{p}}}")
        return out
    if isinstance(st, MatchStmt):
        out = [f"{p}match {_fmt_expr(st.expr)} {{"]
        for pat, body in st.arms:
            out.append(f"{p}    {_fmt_expr(pat)} => {{")
            for s in body:
                out.extend(_fmt_stmt(s, ind + 2))
            out.append(f"{p}    }}")
        out.append(f"{p}}}")
        return out
    return [f"{p}/* unsupported */"]


def _fmt_item(item) -> list[str]:
    if isinstance(item, ImportDecl):
        alias = f" as {item.alias}" if item.alias else ""
        return [f"import {'::'.join(item.path)}{alias};"]
    if isinstance(item, TypeAliasDecl):
        return [f"type {item.name} = {item.target};"]
    if isinstance(item, StructDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        pub = "pub " if item.pub else ""
        out.append(f"{pub}struct {item.name} {{")
        for name, typ in item.fields:
            out.append(f"    {name} {typ},")
        out.append("}")
        return out
    if isinstance(item, EnumDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        pub = "pub " if item.pub else ""
        out.append(f"{pub}enum {item.name} {{")
        for name, fields in item.variants:
            if fields:
                out.append(f"    {name}({', '.join(fields)}),")
            else:
                out.append(f"    {name},")
        out.append("}")
        return out
    if isinstance(item, ExternFnDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        pub = "pub " if item.pub else ""
        us = "unsafe " if item.unsafe else ""
        sig = ", ".join(f"{n} {t}" for n, t in item.params)
        out.append(f'{pub}{us}extern "{item.lib}" fn {item.name}({sig}) -> {item.ret};')
        return out
    if isinstance(item, FnDecl):
        out = []
        if item.doc:
            out.extend([f"/// {line}" for line in item.doc.splitlines()])
        pub = "pub " if item.pub else ""
        impl_kw = "impl " if item.is_impl else ""
        async_kw = "async " if item.async_fn else ""
        sig = ", ".join(f"{n} {t}" for n, t in item.params)
        out.append(f"{pub}{impl_kw}{async_kw}fn {item.name}({sig}) -> {item.ret} {{")
        for st in item.body:
            out.extend(_fmt_stmt(st, 1))
        out.append("}")
        return out
    return []


def fmt(src: str) -> str:
    try:
        prog = parse(src)
    except ParseError:
        out = []
        indent = 0
        for raw in src.splitlines():
            line = raw.strip()
            if line.startswith("}"):
                indent = max(0, indent - 1)
            out.append("    " * indent + line)
            if line.endswith("{"):
                indent += 1
        return "\n".join(out) + "\n"
    out: list[str] = []
    for item in prog.items:
        out.extend(_fmt_item(item))
        out.append("")
    if out:
        out.pop()
    return "\n".join(out) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("file")
    ns = p.parse_args(argv)
    f = Path(ns.file)
    f.write_text(fmt(f.read_text()))
    print("formatted")


if __name__ == "__main__":
    main()
