import argparse
import json
from pathlib import Path

from astra.comptime import run_comptime
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


def lint_text(src: str):
    errs = []
    for i, l in enumerate(src.splitlines(), 1):
        if "\t" in l:
            errs.append((i, "tab character not allowed"))
        if len(l) > 120:
            errs.append((i, "line too long"))
    return errs


def lint_semantic(src: str, filename: str):
    try:
        prog = parse(src, filename=filename)
        run_comptime(prog, filename=filename)
        analyze(prog, filename=filename)
        return []
    except (ParseError, SemanticError) as e:
        return [(0, str(e))]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-semantic", action="store_true")
    ns = p.parse_args(argv)
    src = Path(ns.file).read_text()
    errs = lint_text(src)
    if not ns.no_semantic and ns.file.endswith(".astra"):
        errs.extend(lint_semantic(src, ns.file))
    if errs:
        if ns.json:
            out = [{"line": ln, "message": msg} for ln, msg in errs]
            print(json.dumps(out, indent=2))
        else:
            for ln, msg in errs:
                if ln > 0:
                    print(f"{ns.file}:{ln}: {msg}")
                else:
                    print(msg)
        raise SystemExit(1)
    print("clean")


if __name__ == "__main__":
    main()
