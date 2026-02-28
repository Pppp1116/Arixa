import argparse
from pathlib import Path

from astra.ast import EnumDecl, ExternFnDecl, FnDecl, StructDecl
from astra.parser import parse


def _doc_block(text: str) -> list[str]:
    if not text:
        return []
    return [f"  {line}" for line in text.splitlines()]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("input")
    p.add_argument("-o", "--output", required=True)
    ns = p.parse_args(argv)
    src = Path(ns.input).read_text()
    prog = parse(src, filename=ns.input)
    lines = ["# API", ""]
    for item in prog.items:
        if isinstance(item, StructDecl):
            pub = "pub " if item.pub else ""
            lines.append(f"- `{pub}struct {item.name}`")
            for f, t in item.fields:
                lines.append(f"  - `{f}: {t}`")
            lines.extend(_doc_block(item.doc))
            lines.append("")
        elif isinstance(item, EnumDecl):
            pub = "pub " if item.pub else ""
            lines.append(f"- `{pub}enum {item.name}`")
            for v, tys in item.variants:
                if tys:
                    lines.append(f"  - `{v}({', '.join(tys)})`")
                else:
                    lines.append(f"  - `{v}`")
            lines.extend(_doc_block(item.doc))
            lines.append("")
        elif isinstance(item, ExternFnDecl):
            pub = "pub " if item.pub else ""
            us = "unsafe " if item.unsafe else ""
            sig = ", ".join(f"{n}: {t}" for n, t in item.params)
            lines.append(f'- `{pub}{us}extern "{item.lib}" fn {item.name}({sig}) -> {item.ret}`')
            lines.extend(_doc_block(item.doc))
            lines.append("")
        elif isinstance(item, FnDecl):
            pub = "pub " if item.pub else ""
            impl_kw = "impl " if item.is_impl else ""
            async_kw = "async " if item.async_fn else ""
            sig = ", ".join(f"{n}: {t}" for n, t in item.params)
            lines.append(f"- `{pub}{impl_kw}{async_kw}fn {item.name}({sig}) -> {item.ret}`")
            lines.extend(_doc_block(item.doc))
            lines.append("")
    Path(ns.output).write_text("\n".join(lines).rstrip() + "\n")
    print("docs-generated")


if __name__ == "__main__":
    main()
