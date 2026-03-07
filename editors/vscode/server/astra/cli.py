"""Command line interface implementation for the `astra` executable."""
import argparse
import json
import subprocess
import sys
from pathlib import Path
from astra.build import build
from astra.check import diagnostics_to_json_list, format_diagnostic, run_check_paths, run_check_source
from astra.docgen import main as doc_main
from astra.formatter import fmt, resolve_format_config
from astra.pkg import main as pkg_main
def _discover_astra_files(root: Path) -> list[Path]:
    """Discover Astra source files under a root path, skipping tool/cache dirs."""
    skip_dirs = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", "build", ".astra-build"}
    out: list[Path] = []
    for p in root.rglob("*.astra"):
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.is_file():
            out.append(p)
    out.sort(key=lambda x: x.as_posix())
    return out
def cmd_build(a):
    """Handle the `astra build` subcommand.
    
    Parameters:
        a: Input value used by this routine.
    
    Returns:
        None. May raise `SystemExit` for CLI exit handling.
    """
    state = build(
        a.input,
        a.output,
        a.target,
        kind=a.kind,
        emit_ir=a.emit_ir,
        strict=a.strict,
        freestanding=a.freestanding,
        profile=a.profile,
        overflow=a.overflow,
        sanitize=a.sanitize,
        triple=a.triple,
        links=a.link,
    )
    print(state)
def cmd_check(a):
    """Handle the `astra check` subcommand.
    
    Parameters:
        a: Input value used by this routine.
    
    Returns:
        None. May raise `SystemExit` for CLI exit handling.
    """
    modes = int(bool(a.stdin)) + int(bool(a.files)) + int(bool(a.input))
    if modes != 1:
        raise ValueError("check requires exactly one input mode: <input>, --files, or --stdin")
    if a.stdin:
        src = sys.stdin.read()
        result = run_check_source(
            src,
            filename=a.stdin_filename,
            freestanding=a.freestanding,
            overflow=a.overflow,
            collect_errors=True,
        )
    elif a.files:
        result = run_check_paths(
            a.files,
            freestanding=a.freestanding,
            overflow=a.overflow,
            collect_errors=True,
        )
    else:
        src = Path(a.input).read_text()
        result = run_check_source(
            src,
            filename=a.input,
            freestanding=a.freestanding,
            overflow=a.overflow,
            collect_errors=True,
        )
    if a.json:
        payload = {
            "ok": result.ok,
            "files_checked": list(result.files_checked),
            "diagnostics": diagnostics_to_json_list(result.diagnostics),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for diag in result.diagnostics:
            print(format_diagnostic(diag), file=sys.stderr)
        if result.ok:
            if len(result.files_checked) > 1:
                print(f"ok ({len(result.files_checked)} files)")
            else:
                print("ok")
    if not result.ok:
        raise SystemExit(1)
def cmd_run(a):
    """Handle the `astra run` subcommand.
    
    Parameters:
        a: Input value used by this routine.
    
    Returns:
        None. May raise `SystemExit` for CLI exit handling.
    """
    out = Path(".astra-build") / (Path(a.input).stem + ".py")
    build(a.input, str(out), "py")
    raise SystemExit(subprocess.call([sys.executable, str(out)] + a.args))
def cmd_test(a):
    """Handle the `astra test` subcommand.
    
    Parameters:
        a: Input value used by this routine.
    
    Returns:
        None. May raise `SystemExit` for CLI exit handling.
    """
    args = [sys.executable, "-m", "pytest", "-q"]
    if a.kind == "unit":
        args += ["-k", "not integration and not e2e"]
    elif a.kind == "integration":
        args += ["-k", "integration"]
    elif a.kind == "e2e":
        args += ["-k", "e2e"]
    raise SystemExit(subprocess.call(args))
def cmd_fmt(a):
    """Handle the `astra fmt` subcommand.
    
    Parameters:
        a: Input value used by this routine.
    
    Returns:
        None. May raise `SystemExit` for CLI exit handling.
    """
    targets: list[Path]
    if a.files:
        targets = [Path(path) for path in a.files]
    else:
        targets = _discover_astra_files(Path.cwd())
    bad: list[str] = []
    for fp in targets:
        src = fp.read_text()
        out = fmt(src, config=resolve_format_config(fp))
        if a.check:
            if out != src:
                bad.append(str(fp))
            continue
        fp.write_text(out)
    if a.check:
        if bad:
            for path in bad:
                print(f"not formatted: {path}", file=sys.stderr)
            raise SystemExit(1)
        print("ok")
        return
    print("formatted")
def cmd_doc(a):
    """Handle the `astra doc` subcommand.
    
    Parameters:
        a: Input value used by this routine.
    
    Returns:
        None. May raise `SystemExit` for CLI exit handling.
    """
    args = [a.input, "-o", a.output]
    doc_main(args)
def cmd_selfhost(a):
    """Handle the `astra selfhost` subcommand.
    
    The selfhost/compiler.astra file contains a staged compilation pipeline
    (source analysis, IR construction, validation, code generation) that can
    be compiled via the Python backend.  However, the CLI entry-point reports
    the feature as unavailable until the full self-hosting contract (bootstrap
    + verification) is finalized.
    Parameters:
        a: Input value used by this routine.
    
    Returns:
        None. May raise `SystemExit` for CLI exit handling.
    """
    print(
        "selfhost-unavailable: selfhost/compiler.astra contains a staged pipeline "
        "but the full self-hosting bootstrap is not yet finalized",
        file=sys.stderr,
    )
    raise SystemExit(1)
def cmd_pkg(a):
    """Handle the `astra pkg` subcommand.
    
    Parameters:
        a: Input value used by this routine.
    
    Returns:
        None. May raise `SystemExit` for CLI exit handling.
    """
    pkg_main(a.args)
def main(argv=None):
    """CLI-style entrypoint for this module.
    
    Parameters:
        argv: Optional CLI arguments passed instead of process argv.
    
    Returns:
        Value produced by the routine, if any.
    """
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("build")
    b.add_argument("input")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--target", choices=["py", "llvm", "native"], default="py")
    b.add_argument("--kind", choices=["exe", "lib"], default="exe")
    b.add_argument("--emit-ir")
    b.add_argument("--strict", action="store_true")
    b.add_argument("--freestanding", action="store_true")
    b.add_argument("--profile", choices=["debug", "release"], default="debug")
    b.add_argument("--overflow", choices=["trap", "wrap", "debug"], default="debug")
    b.add_argument("--sanitize", choices=["address", "undefined", "thread"])
    b.add_argument("--triple")
    b.add_argument("--link", action="append", default=[])
    b.set_defaults(func=cmd_build)
    c = sp.add_parser("check")
    c.add_argument("input", nargs="?")
    c.add_argument("--files", nargs="+")
    c.add_argument("--stdin", action="store_true")
    c.add_argument("--stdin-filename", default="<stdin>")
    c.add_argument("--json", action="store_true")
    c.add_argument("--freestanding", action="store_true")
    c.add_argument("--overflow", choices=["trap", "wrap", "debug"], default="trap")
    c.set_defaults(func=cmd_check)
    r = sp.add_parser("run")
    r.add_argument("input")
    r.add_argument("args", nargs="*")
    r.set_defaults(func=cmd_run)
    t = sp.add_parser("test")
    t.add_argument("--kind", choices=["unit", "integration", "e2e"], default="unit")
    t.set_defaults(func=cmd_test)
    f = sp.add_parser("fmt")
    f.add_argument("files", nargs="*")
    f.add_argument("--check", action="store_true")
    f.set_defaults(func=cmd_fmt)
    d = sp.add_parser("doc")
    d.add_argument("input")
    d.add_argument("-o", "--output", required=True)
    d.set_defaults(func=cmd_doc)
    s = sp.add_parser("selfhost")
    s.set_defaults(func=cmd_selfhost)
    k = sp.add_parser("pkg")
    k.add_argument("args", nargs=argparse.REMAINDER)
    k.set_defaults(func=cmd_pkg)
    a = p.parse_args(argv)
    try:
        a.func(a)
    except Exception as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)
if __name__ == "__main__":
    main()
