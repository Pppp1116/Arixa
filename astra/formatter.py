import argparse
from pathlib import Path

def fmt(src: str) -> str:
    out=[]; indent=0
    for raw in src.splitlines():
        line=raw.strip()
        if line.startswith('}'): indent=max(0,indent-1)
        out.append('    '*indent + line)
        if line.endswith('{'): indent+=1
    return '\n'.join(out)+"\n"

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('file'); ns=p.parse_args(argv)
    f=Path(ns.file); f.write_text(fmt(f.read_text())); print('formatted')
