import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from astra.build import build
from astra.profiler import profiler
from astra.check import diagnostics_to_json_list, format_diagnostic, run_check_paths, run_check_source
from astra.docgen import main as doc_main
from astra.formatter import fmt


def cmd_build(a):
    state = build(
        a.input,
        a.output,
        a.target,
        emit_ir=a.emit_ir,
        strict=a.strict,
        freestanding=a.freestanding,
        profile=a.profile,
        overflow=a.overflow,
        triple=a.triple,
        profile_compile=a.profile_compile,
        threads=a.threads,
        opt_size=getattr(a, "opt_size", False),
    )
    if a.profile_compile and a.profile_json:
        print(profiler.to_json())
    print(state)


def cmd_check(a):
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
        if result.ok:
            if len(result.files_checked) > 1:
                print(f"ok ({len(result.files_checked)} files)")
            else:
                print("ok")
        else:
            for diag in result.diagnostics:
                print(format_diagnostic(diag), file=sys.stderr)
                for note in diag.notes:
                    if note.span is None:
                        print(f"  note: {note.message}", file=sys.stderr)
                    else:
                        print(
                            f"  note: {note.span.filename}:{note.span.line}:{note.span.col}: {note.message}",
                            file=sys.stderr,
                        )
    if not result.ok:
        raise SystemExit(1)


def cmd_run(a):
    out = Path(".astra-build") / (Path(a.input).stem + ".py")
    build(a.input, str(out), "py", profile_compile=a.profile_compile, threads=a.threads, opt_size=getattr(a, "opt_size", False))
    raise SystemExit(subprocess.call([sys.executable, str(out)] + a.args))


def cmd_test(a):
    args = [sys.executable, "-m", "pytest", "-q"]
    if a.kind == "unit":
        args += ["-k", "not integration and not e2e"]
    elif a.kind == "integration":
        args += ["-k", "integration"]
    elif a.kind == "e2e":
        args += ["-k", "e2e"]
    raise SystemExit(subprocess.call(args))


def cmd_fmt(a):
    bad: list[str] = []
    for path in a.files:
        fp = Path(path)
        src = fp.read_text()
        out = fmt(src)
        if a.check:
            if out != src:
                bad.append(path)
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
    args = [a.input, "-o", a.output]
    doc_main(args)


def cmd_selfhost(a):
    print(
        "selfhost-unavailable: selfhost/compiler.astra is a placeholder file copier, "
        "not a real self-hosted compiler",
        file=sys.stderr,
    )
    raise SystemExit(1)


def _add_global_flags(ap: argparse.ArgumentParser) -> None:
    ap.add_argument("--profile-compile", action="store_true", dest="profile_compile")
    ap.add_argument("--profile-json", action="store_true", dest="profile_json")
    ap.add_argument("--threads", type=int, default=os.cpu_count())


def cmd_bench(a):
    # Run 3 times and report median per-phase and total. Always enable profiling.
    runs = []
    for _ in range(3):
        profiler.enable(False)
        state = build(
            a.input,
            a.output,
            a.target,
            emit_ir=a.emit_ir,
            strict=a.strict,
            freestanding=a.freestanding,
            profile=a.profile,
            overflow=a.overflow,
            triple=a.triple,
            profile_compile=True,
            threads=a.threads,
            opt_size=getattr(a, "opt_size", False),
        )
        # Capture JSON each run
        payload = json.loads(profiler.to_json() or "{}")
        runs.append(payload)
    # Compute medians
    def median(xs):
        ys = sorted(xs)
        n = len(ys)
        if n % 2 == 1:
            return ys[n//2]
        return 0.5 * (ys[n//2 - 1] + ys[n//2])

    # Aggregate phase medians
    phases = {}
    for r in runs:
        for k, v in r.get("phases", {}).items():
            phases.setdefault(k, []).append(v)
    phase_medians = {k: median(vs) for k, vs in phases.items()}
    total_median = median([r.get("total", 0.0) for r in runs])
    out = {
        "phase_median_s": dict(sorted(phase_medians.items())),
        "total_median_s": total_median,
        "threads": a.threads or 0,
        "target": a.target,
    }
    print(json.dumps(out, indent=2, sort_keys=True))


def main(argv=None):
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    b = sp.add_parser("build")
    b.add_argument("input")
    b.add_argument("-o", "--output", required=True)
    b.add_argument("--target", choices=["py", "llvm", "native"], default="py")
    b.add_argument("--emit-ir")
    b.add_argument("--strict", action="store_true")
    b.add_argument("--freestanding", action="store_true")
    b.add_argument("--profile", choices=["debug", "release"], default="debug")
    b.add_argument("--overflow", choices=["trap", "wrap", "debug"], default="debug")
    b.add_argument("--triple")
    b.add_argument("--opt-size", action="store_true", dest="opt_size")
    _add_global_flags(b)
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
    r.add_argument("--opt-size", action="store_true", dest="opt_size")
    _add_global_flags(r)
    r.set_defaults(func=cmd_run)

    t = sp.add_parser("test")
    t.add_argument("--kind", choices=["unit", "integration", "e2e"], default="unit")
    t.set_defaults(func=cmd_test)

    f = sp.add_parser("fmt")
    f.add_argument("files", nargs="+")
    f.add_argument("--check", action="store_true")
    f.set_defaults(func=cmd_fmt)

    d = sp.add_parser("doc")
    d.add_argument("input")
    d.add_argument("-o", "--output", required=True)
    d.set_defaults(func=cmd_doc)

    s = sp.add_parser("selfhost")
    s.set_defaults(func=cmd_selfhost)

    bench = sp.add_parser("bench")
    bench.add_argument("input")
    bench.add_argument("-o", "--output", required=True)
    bench.add_argument("--target", choices=["py", "llvm", "native"], default="py")
    bench.add_argument("--emit-ir")
    bench.add_argument("--strict", action="store_true")
    bench.add_argument("--freestanding", action="store_true")
    bench.add_argument("--profile", choices=["debug", "release"], default="debug")
    bench.add_argument("--overflow", choices=["trap", "wrap", "debug"], default="debug")
    bench.add_argument("--triple")
    bench.add_argument("--opt-size", action="store_true", dest="opt_size")
    _add_global_flags(bench)
    bench.set_defaults(func=cmd_bench)

    a = p.parse_args(argv)
    try:
        a.func(a)
    except Exception as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
