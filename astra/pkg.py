import argparse
import json
import tomllib
from pathlib import Path


REG = Path("Astra.lock")
MANIFEST = Path("Astra.toml")


def _diag(msg: str) -> str:
    return f"PKG {MANIFEST}:1:1: {msg}"


def _load_manifest() -> dict:
    if not MANIFEST.exists():
        return {"name": "app", "deps": {}}
    data = tomllib.loads(MANIFEST.read_text())
    name = data.get("name", "app")
    deps = data.get("deps", {})
    if not isinstance(name, str):
        raise ValueError(_diag("name must be a string"))
    if not isinstance(deps, dict):
        raise ValueError(_diag("deps must be a table"))
    out: dict[str, str] = {}
    for k, v in deps.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError(_diag("dependency entries must be string = string"))
        out[k] = v
    return {"name": name, "deps": out}


def _write_manifest(data: dict):
    lines = [f'name = "{data["name"]}"']
    if data["deps"]:
        lines.append("")
        lines.append("[deps]")
        for k, v in sorted(data["deps"].items()):
            lines.append(f'{k} = "{v}"')
    MANIFEST.write_text("\n".join(lines) + "\n")


def resolve(deps: dict[str, str]) -> dict[str, str]:
    return dict(sorted(deps.items()))


def main(argv=None):
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)
    i = sp.add_parser("init")
    i.add_argument("name")
    a = sp.add_parser("add")
    a.add_argument("dep")
    a.add_argument("ver")
    sp.add_parser("lock")
    ns = p.parse_args(argv)
    data = _load_manifest()
    if ns.cmd == "init":
        data = {"name": ns.name, "deps": {}}
        _write_manifest(data)
        print("initialized")
        return
    if ns.cmd == "add":
        data["deps"][ns.dep] = ns.ver
        _write_manifest(data)
        print("added")
        return
    if ns.cmd == "lock":
        REG.write_text(json.dumps(resolve(data["deps"]), indent=2) + "\n")
        print("locked")
        return


if __name__ == "__main__":
    main()
