import argparse
from pathlib import Path

def lint_text(src: str):
    errs=[]
    for i,l in enumerate(src.splitlines(),1):
        if '\t' in l: errs.append((i,'tab character not allowed'))
        if len(l)>120: errs.append((i,'line too long'))
    return errs

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument('file'); ns=p.parse_args(argv)
    errs = lint_text(Path(ns.file).read_text())
    if errs:
        for ln,msg in errs: print(f"{ns.file}:{ln}: {msg}")
        raise SystemExit(1)
    print('clean')
