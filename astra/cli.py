import argparse
import subprocess
import sys
from pathlib import Path

from astra.build import build
from astra.comptime import run_comptime
from astra.parser import parse
from astra.semantic import analyze


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
    )
    print(state)


def cmd_check(a):
    src = Path(a.input).read_text()
    prog = parse(src, filename=a.input)
    overflow_mode = "trap" if a.overflow == "debug" else a.overflow
    run_comptime(prog, filename=a.input, overflow_mode=overflow_mode)
    analyze(prog, filename=a.input, freestanding=a.freestanding)
    print("ok")


def cmd_run(a):
    out = Path(".astra-build") / (Path(a.input).stem + ".py")
    build(a.input, str(out), "py")
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


def cmd_selfhost(a):
    print(
        "selfhost-unavailable: selfhost/compiler.astra is a placeholder file copier, "
        "not a real self-hosted compiler",
        file=sys.stderr,
    )
    raise SystemExit(1)


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
    b.set_defaults(func=cmd_build)

    c = sp.add_parser("check")
    c.add_argument("input")
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

    s = sp.add_parser("selfhost")
    s.set_defaults(func=cmd_selfhost)

    a = p.parse_args(argv)
    try:
        a.func(a)
    except Exception as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
