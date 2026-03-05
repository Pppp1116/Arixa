"""Package-manager helpers for Astra.toml dependency workflows."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path
import ctypes.util
from urllib.request import urlopen

try:
    import tomllib
except Exception:  # pragma: no cover - fallback for older runtimes
    import tomli as tomllib


REG = Path("Astra.lock")
MANIFEST = Path("Astra.toml")
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/Pppp1116/ASTRA/main/registry/packages.json"


def _diag(msg: str) -> str:
    return f"PKG {MANIFEST}:1:1: {msg}"


def _package_home() -> Path:
    env = None
    try:
        import os

        env = os.environ.get("ASTRA_PKG_HOME")
    except Exception:
        env = None
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".astra" / "packages").resolve()


def _load_manifest() -> dict:
    if not MANIFEST.exists():
        return {"name": "app", "deps": {}, "project_style": False}
    data = tomllib.loads(MANIFEST.read_text())

    if "project" in data and isinstance(data["project"], dict):
        name = data["project"].get("name", "app")
        deps = data.get("dependencies", {})
        if not isinstance(name, str):
            raise ValueError(_diag("project.name must be a string"))
        if not isinstance(deps, dict):
            raise ValueError(_diag("dependencies must be a table"))
        out: dict[str, str] = {}
        for k, v in deps.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v
        return {"name": name, "deps": out, "project_style": True}

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
    # Merge modern dependencies if they exist.
    deps2 = data.get("dependencies", {})
    if isinstance(deps2, dict):
        for k, v in deps2.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v
    return {"name": name, "deps": out, "project_style": False}


def _write_manifest(data: dict) -> None:
    deps = dict(sorted(data.get("deps", {}).items()))
    name = data.get("name", "app")
    if data.get("project_style"):
        lines = [
            "[project]",
            f'name = "{name}"',
            'version = "0.1.0"',
            "",
            "[dependencies]",
        ]
        for k, v in deps.items():
            lines.append(f'{k} = "{v}"')
        MANIFEST.write_text("\n".join(lines).rstrip() + "\n")
        return

    lines = [f'name = "{name}"']
    if deps:
        lines.append("")
        lines.append("[deps]")
        for k, v in deps.items():
            lines.append(f'{k} = "{v}"')
        lines.append("")
        lines.append("[dependencies]")
        for k, v in deps.items():
            lines.append(f'{k} = "{v}"')
    MANIFEST.write_text("\n".join(lines) + "\n")


def resolve(deps: dict[str, str]) -> dict[str, str]:
    return dict(sorted(deps.items()))


def _fetch_registry() -> dict[str, dict]:
    import os

    explicit_path = os.environ.get("ASTRA_REGISTRY_PATH")
    if explicit_path:
        return json.loads(Path(explicit_path).read_text())

    url = os.environ.get("ASTRA_REGISTRY_URL", _DEFAULT_REGISTRY_URL)
    if not url.startswith(("https://", "http://")):
        raise ValueError(_diag(f"registry URL must use http(s) scheme: {url}"))
    try:
        with urlopen(url, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        local = _REPO_ROOT / "registry" / "packages.json"
        if local.exists():
            return json.loads(local.read_text())
        raise ValueError(_diag("failed to fetch package registry")) from exc


def _ensure_package_installed(name: str, version: str, repo: str) -> Path:
    dst = _package_home() / name / version
    if dst.exists():
        return dst
    dst.parent.mkdir(parents=True, exist_ok=True)

    # Local path support for tests/private setups.
    if repo.startswith("file://"):
        src = Path(repo[len("file://") :]).resolve()
        shutil.copytree(src, dst)
        return dst
    maybe_path = Path(repo)
    if maybe_path.exists():
        shutil.copytree(maybe_path.resolve(), dst)
        return dst

    git = shutil.which("git")
    if git is None:
        raise ValueError(_diag("git is required to install packages from repositories"))
    cp = subprocess.run([git, "clone", "--depth", "1", repo, str(dst)], capture_output=True, text=True)
    if cp.returncode != 0:
        detail = (cp.stderr or cp.stdout).strip()
        raise ValueError(_diag(f"failed to clone package repository {repo}{': ' + detail if detail else ''}"))
    return dst


def _load_package_manifest(pkg_dir: Path) -> dict:
    mf = pkg_dir / "Astra.toml"
    if not mf.exists():
        return {}
    try:
        return tomllib.loads(mf.read_text())
    except Exception:
        return {}


def _platform_key() -> str:
    import sys

    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return sys.platform


def _native_lib_installed(lib: str) -> bool:
    if lib == "c":
        return True
    return ctypes.util.find_library(lib) is not None


def _maybe_run_install_hint(pkg_name: str, pkg_manifest: dict) -> None:
    native = pkg_manifest.get("native", {})
    install = pkg_manifest.get("install", {})
    if not isinstance(native, dict):
        native = {}
    if not isinstance(install, dict):
        install = {}
    libs = native.get("libs", [])
    if not isinstance(libs, list):
        return
    missing = [lib for lib in libs if isinstance(lib, str) and lib and not _native_lib_installed(lib)]
    if not missing:
        return

    plat = _platform_key()
    cmd = install.get(plat) if isinstance(install, dict) else None
    hint = native.get("install_hint") if isinstance(native, dict) else None
    if cmd:
        print(f"native library for `{pkg_name}` appears missing: {', '.join(missing)}")
        print(f"suggested install command ({plat}): {cmd}")
        try:
            import os

            auto = os.environ.get("ASTPM_AUTO_YES", "").lower()
        except Exception:
            auto = ""
        run_it = auto in {"1", "true", "yes", "y"}
        if not run_it:
            try:
                ans = input("run this command now? [y/N]: ").strip().lower()
            except EOFError:
                ans = ""
            run_it = ans in {"y", "yes"}
        if run_it:
            subprocess.run(cmd, shell=True, check=False)
        return
    if isinstance(hint, str) and hint.strip():
        print(f"native library for `{pkg_name}` appears missing: {', '.join(missing)}")
        print(hint.strip())


def _write_lock(data: dict[str, str]) -> None:
    REG.write_text(json.dumps(resolve(data), indent=2) + "\n")


def _cmd_init(name: str) -> None:
    data = {"name": name, "deps": {}, "project_style": False}
    _write_manifest(data)
    print("initialized")


def _cmd_add(pkg: str, ver: str | None) -> None:
    data = _load_manifest()
    if ver is not None:
        # Backward-compatible mode: exact version provided.
        data["deps"][pkg] = ver
        _write_manifest(data)
        print("added")
        return

    registry = _fetch_registry()
    entry = registry.get(pkg)
    if not isinstance(entry, dict):
        raise ValueError(_diag(f"package `{pkg}` not found in registry; try `astpm search {pkg}`"))
    version = str(entry.get("version", "0.0.0"))
    repo = str(entry.get("repo", "")).strip()
    if not repo:
        raise ValueError(_diag(f"package `{pkg}` has no repository configured in registry"))

    pkg_dir = _ensure_package_installed(pkg, version, repo)
    pkg_manifest = _load_package_manifest(pkg_dir)
    _maybe_run_install_hint(pkg, pkg_manifest)

    data["deps"][pkg] = version
    _write_manifest(data)
    _write_lock(data["deps"])
    print(f"✓ Added {pkg} {version}")
    print(f'  Import with: import "{pkg}";')


def _cmd_remove(pkg: str) -> None:
    data = _load_manifest()
    data["deps"].pop(pkg, None)
    _write_manifest(data)
    _write_lock(data["deps"])
    pkg_root = _package_home() / pkg
    if pkg_root.exists():
        shutil.rmtree(pkg_root, ignore_errors=True)
    print(f"removed {pkg}")


def _cmd_list() -> None:
    root = _package_home()
    if not root.exists():
        print("no packages installed")
        return
    rows: list[str] = []
    for pkg_dir in sorted([p for p in root.iterdir() if p.is_dir()]):
        versions = sorted([p.name for p in pkg_dir.iterdir() if p.is_dir()], reverse=True)
        if versions:
            rows.append(f"{pkg_dir.name} {versions[0]}")
    if not rows:
        print("no packages installed")
        return
    for row in rows:
        print(row)


def _cmd_search(query: str) -> None:
    registry = _fetch_registry()
    q = query.lower()
    rows = []
    for name, meta in sorted(registry.items()):
        if not isinstance(meta, dict):
            continue
        desc = str(meta.get("description", ""))
        if q and q not in name.lower() and q not in desc.lower():
            continue
        rows.append((name, str(meta.get("version", "")), desc))
    if not rows:
        print("no packages found")
        return
    for name, ver, desc in rows:
        print(f"{name} {ver} - {desc}")


def _cmd_update() -> None:
    data = _load_manifest()
    if not data["deps"]:
        print("no dependencies to update")
        return
    registry = _fetch_registry()
    changed = 0
    for name in sorted(list(data["deps"].keys())):
        entry = registry.get(name)
        if not isinstance(entry, dict):
            continue
        latest = str(entry.get("version", "")).strip()
        repo = str(entry.get("repo", "")).strip()
        if not latest or not repo:
            continue
        if data["deps"].get(name) == latest:
            continue
        _ensure_package_installed(name, latest, repo)
        data["deps"][name] = latest
        changed += 1
    _write_manifest(data)
    _write_lock(data["deps"])
    print(f"updated {changed} package(s)")


def _cmd_publish() -> None:
    if not MANIFEST.exists():
        raise ValueError(_diag("Astra.toml not found in current directory"))
    data = tomllib.loads(MANIFEST.read_text())
    pkg = data.get("package", {})
    if not isinstance(pkg, dict):
        raise ValueError(_diag("package manifest must contain a [package] table"))
    name = pkg.get("name")
    version = pkg.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        raise ValueError(_diag("[package] must include string fields `name` and `version`"))
    print(f"package `{name}` ({version}) looks valid")
    print("next step:")
    print("1. push your package repository")
    print("2. edit registry/packages.json and add your package entry")
    print("3. open a PR against the ASTRA repository")


def main(argv=None):
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    i = sp.add_parser("init")
    i.add_argument("name")

    a = sp.add_parser("add")
    a.add_argument("dep")
    a.add_argument("ver", nargs="?")

    rm = sp.add_parser("remove")
    rm.add_argument("dep")

    s = sp.add_parser("search")
    s.add_argument("query", nargs="?", default="")

    sp.add_parser("list")
    sp.add_parser("update")
    sp.add_parser("publish")
    sp.add_parser("lock")

    ns = p.parse_args(argv)
    if ns.cmd == "init":
        _cmd_init(ns.name)
        return
    if ns.cmd == "add":
        _cmd_add(ns.dep, ns.ver)
        return
    if ns.cmd == "remove":
        _cmd_remove(ns.dep)
        return
    if ns.cmd == "search":
        _cmd_search(ns.query)
        return
    if ns.cmd == "list":
        _cmd_list()
        return
    if ns.cmd == "update":
        _cmd_update()
        return
    if ns.cmd == "publish":
        _cmd_publish()
        return
    if ns.cmd == "lock":
        data = _load_manifest()
        _write_lock(data["deps"])
        print("locked")
        return


if __name__ == "__main__":
    main()
