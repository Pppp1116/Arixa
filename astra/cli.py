import argparse, subprocess, sys
from pathlib import Path
from astra.build import build

def cmd_build(a):
    state = build(a.input, a.output, a.target)
    print(state)

def cmd_run(a):
    out = Path('.astra-build') / (Path(a.input).stem + '.py')
    build(a.input, str(out), 'py')
    raise SystemExit(subprocess.call([sys.executable, str(out)] + a.args))

def cmd_test(_):
    raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', '-q']))

def cmd_selfhost(a):
    c1='build/selfhost_compiler.py'; c2='build/selfhost_compiler_round2.py'
    build('selfhost/compiler.astra', c1, 'py')
    subprocess.check_call([sys.executable, c1, 'selfhost/compiler.astra', c2])
    print('selfhost-ok' if Path(c2).exists() else 'selfhost-fail')

def main(argv=None):
    p=argparse.ArgumentParser()
    sp=p.add_subparsers(dest='cmd', required=True)
    b=sp.add_parser('build'); b.add_argument('input'); b.add_argument('-o','--output', required=True); b.add_argument('--target', choices=['py','x86_64'], default='py'); b.set_defaults(func=cmd_build)
    r=sp.add_parser('run'); r.add_argument('input'); r.add_argument('args', nargs='*'); r.set_defaults(func=cmd_run)
    t=sp.add_parser('test'); t.set_defaults(func=cmd_test)
    s=sp.add_parser('selfhost'); s.set_defaults(func=cmd_selfhost)
    a=p.parse_args(argv); a.func(a)

if __name__ == '__main__':
    main()
