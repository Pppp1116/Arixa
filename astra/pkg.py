import argparse, json
from pathlib import Path

REG=Path('Astra.lock')

def resolve(deps: dict[str,str]) -> dict[str,str]:
    return dict(sorted(deps.items()))

def main(argv=None):
    p=argparse.ArgumentParser(); sp=p.add_subparsers(dest='cmd', required=True)
    i=sp.add_parser('init'); i.add_argument('name')
    a=sp.add_parser('add'); a.add_argument('dep'); a.add_argument('ver')
    l=sp.add_parser('lock')
    ns=p.parse_args(argv)
    manifest=Path('Astra.toml')
    data={'name':'app','deps':{}}
    if manifest.exists():
        for line in manifest.read_text().splitlines():
            if '=' in line:
                k,v=[x.strip() for x in line.split('=',1)]
                if k.startswith('dep.'): data['deps'][k[4:]]=v
    if ns.cmd=='init':
        manifest.write_text(f"name = {ns.name}\n")
    elif ns.cmd=='add':
        with manifest.open('a') as f: f.write(f"dep.{ns.dep} = {ns.ver}\n")
    elif ns.cmd=='lock':
        REG.write_text(json.dumps(resolve(data['deps']), indent=2))
        print('locked')
