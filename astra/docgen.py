import argparse
from pathlib import Path
from astra.parser import parse

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('input'); p.add_argument('-o','--output', required=True); ns=p.parse_args(argv)
    prog=parse(Path(ns.input).read_text())
    lines=['# API']
    for fn in prog.items:
        sig=', '.join(f"{n}: {t}" for n,t in fn.params)
        g=f"<{', '.join(fn.generics)}>" if fn.generics else ''
        lines.append(f"- `{fn.name}{g}({sig}) -> {fn.ret}`")
    Path(ns.output).write_text('\n'.join(lines)+'\n')
    print('docs-generated')
