import argparse
from pathlib import Path

from astra.ast import *
from astra.parser import ParseError, parse


def _fmt_expr(e) -> str:
    if isinstance(e, BoolLit):
        return "true" if e.value else "false"
    if isinstance(e, NilLit):
        return "nil"
    if isinstance(e, Literal):
        if isinstance(e.value, str):
            return repr(e.value).replace("'", '"')
        return str(e.value)
    if isinstance(e, Name):
        return e.value
    if isinstance(e, AwaitExpr):
        return f"await {_fmt_expr(e.expr)}"
    if isinstance(e, Unary):
        return f"{e.op}{_fmt_expr(e.expr)}"
    if isinstance(e, Binary):
        return f"{_fmt_expr(e.left)} {e.op} {_fmt_expr(e.right)}"
    if isinstance(e, Call):
        return f"{_fmt_expr(e.fn)}({', '.join(_fmt_expr(a) for a in e.args)})"
    if isinstance(e, IndexExpr):
        return f"{_fmt_expr(e.obj)}[{_fmt_expr(e.index)}]"
    if isinstance(e, FieldExpr):
        return f"{_fmt_expr(e.obj)}.{e.field}"
    if isinstance(e, ArrayLit):
        return f"[{', '.join(_fmt_expr(x) for x in e.elements)}]"
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
