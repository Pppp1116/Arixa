"""Linting helpers for style issues plus semantic lint integration."""

import argparse
import json
from pathlib import Path

from astra.comptime import run_comptime
from astra.parser import ParseError, parse
from astra.semantic import SemanticError, analyze


def lint_text(src: str):
    """Run lint checks and return collected diagnostics.
    
    Parameters:
        src: Astra source text to process.
    
    Returns:
        Value produced by the routine, if any.
    """
    errs = []
    for i, l in enumerate(src.splitlines(), 1):
        if "\t" in l:
            errs.append((i, "tab character not allowed"))
        if len(l) > 120:
            errs.append((i, "line too long"))
    return errs


def lint_semantic(src: str, filename: str):
    """Run lint checks and return collected diagnostics.
    
    Parameters:
        src: Astra source text to process.
        filename: Filename context used for diagnostics or path resolution.
    
    Returns:
        Value produced by the routine, if any.
    """
    try:
        prog = parse(src, filename=filename)
        run_comptime(prog, filename=filename)
        analyze(prog, filename=filename)
        return []
    except (ParseError, SemanticError) as e:
        return [(0, str(e))]


def _collect_targets(path: str) -> list[Path]:
    target = Path(path)
    if target.is_file():
        return [target]
    if target.is_dir():
        files = [p for p in target.rglob("*.arixa") if p.is_file()]
        files.sort(key=lambda p: p.as_posix())
        return files
    raise FileNotFoundError(path)


def main(argv=None):
    """CLI-style entrypoint for this module.
    
    Parameters:
        argv: Optional CLI arguments passed instead of process argv.
    
    Returns:
        Value produced by the routine, if any.
    """
    p = argparse.ArgumentParser()
    p.add_argument("path")
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-semantic", action="store_true")
    ns = p.parse_args(argv)
    targets = _collect_targets(ns.path)
    errs: list[tuple[str, int, str]] = []
    for fp in targets:
        src = fp.read_text()
        text_errs = lint_text(src)
        errs.extend((str(fp), ln, msg) for ln, msg in text_errs)
        if not ns.no_semantic and fp.suffix == ".arixa":
            sem_errs = lint_semantic(src, str(fp))
            errs.extend((str(fp), ln, msg) for ln, msg in sem_errs)
    if errs:
        if ns.json:
            out = [{"file": file, "line": ln, "message": msg} for file, ln, msg in errs]
            print(json.dumps(out, indent=2))
        else:
            for file, ln, msg in errs:
                if ln > 0:
                    print(f"{file}:{ln}: {msg}")
                else:
                    print(f"{file}: {msg}")
        raise SystemExit(1)
    print("clean")


if __name__ == "__main__":
    main()
