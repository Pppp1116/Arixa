"""Package-manager helpers for Astra.toml dependency workflows."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
import ctypes.util
import re
from typing import Any
from urllib.request import urlopen

try:
    import tomllib
except Exception:  # pragma: no cover - fallback for older runtimes
    import tomli as tomllib

REG = Path("Astra.lock")
MANIFEST = Path("Astra.toml")
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_REGISTRY_URL = "https://raw.githubusercontent.com/Pppp1116/ASTRA/main/registry/packages.json"
_LOCK_SCHEMA_VERSION = 1
_REGISTRY_CACHE_ENV = "ASTRA_REGISTRY_CACHE"


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


def _registry_cache_path() -> Path:
    import os

    explicit = os.environ.get(_REGISTRY_CACHE_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (_package_home().parent / "registry-cache.json").resolve()


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


_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _is_semver(version: str) -> bool:
    return _SEMVER_RE.match(version.strip()) is not None


def _parse_semver(version: str) -> tuple[int, int, int] | None:
    if not _is_semver(version):
        return None
    major, minor, patch = version.strip().split(".")
    return (int(major), int(minor), int(patch))


def _cmp_semver(a: str, b: str) -> int:
    pa = _parse_semver(a)
    pb = _parse_semver(b)
    if pa is None and pb is None:
        return (a > b) - (a < b)
    if pa is None:
        return -1
    if pb is None:
        return 1
    return (pa > pb) - (pa < pb)


def _semver_sort_key(version: str) -> tuple[int, int, int, str]:
    parsed = _parse_semver(version)
    if parsed is None:
        return (-1, -1, -1, version)
    return (parsed[0], parsed[1], parsed[2], "")


def _wildcard_bounds(spec: str) -> tuple[tuple[int, int, int], tuple[int, int, int]] | None:
    parts = spec.split(".")
    if not 1 <= len(parts) <= 3:
        return None
    nums: list[int] = []
    wildcard_at: int | None = None
    for idx, part in enumerate(parts):
        p = part.strip().lower()
        if p in {"*", "x"}:
            wildcard_at = idx
            break
        if not p.isdigit():
            return None
        nums.append(int(p))
    if wildcard_at is None:
        return None
    while len(nums) < 3:
        nums.append(0)
    low = (nums[0], nums[1], nums[2])
    if wildcard_at == 0:
        high = (10**9, 0, 0)
    elif wildcard_at == 1:
        high = (nums[0] + 1, 0, 0)
    else:
        high = (nums[0], nums[1] + 1, 0)
    return (low, high)


def _matches_semver_constraint(version: str, constraint: str) -> bool:
    c = constraint.strip()
    if not c or c == "*":
        return True

    pv = _parse_semver(version)
    if pv is None:
        return version == c

    if c.startswith("^"):
        base = _parse_semver(c[1:].strip())
        if base is None:
            return False
        low = base
        if base[0] > 0:
            high = (base[0] + 1, 0, 0)
        elif base[1] > 0:
            high = (0, base[1] + 1, 0)
        else:
            high = (0, 0, base[2] + 1)
        return low <= pv < high

    if c.startswith("~"):
        base = _parse_semver(c[1:].strip())
        if base is None:
            return False
        low = base
        high = (base[0], base[1] + 1, 0)
        return low <= pv < high

    wild = _wildcard_bounds(c)
    if wild is not None:
        low, high = wild
        return low <= pv < high

    comparators = [x.strip() for x in c.replace(" ", ",").split(",") if x.strip()]
    if comparators and all(token.startswith((">=", "<=", ">", "<")) for token in comparators):
        for token in comparators:
            if token.startswith(">="):
                ref = _parse_semver(token[2:].strip())
                if ref is None or not (pv >= ref):
                    return False
            elif token.startswith("<="):
                ref = _parse_semver(token[2:].strip())
                if ref is None or not (pv <= ref):
                    return False
            elif token.startswith(">"):
                ref = _parse_semver(token[1:].strip())
                if ref is None or not (pv > ref):
                    return False
            elif token.startswith("<"):
                ref = _parse_semver(token[1:].strip())
                if ref is None or not (pv < ref):
                    return False
        return True

    exact = _parse_semver(c)
    if exact is not None:
        return pv == exact

    return version == c


def _registry_versions(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    versions = entry.get("versions")
    out: dict[str, dict[str, Any]] = {}
    if isinstance(versions, dict):
        for ver, meta in versions.items():
            if isinstance(ver, str) and isinstance(meta, dict):
                out[ver] = dict(meta)
    elif isinstance(versions, list):
        for item in versions:
            if not isinstance(item, dict):
                continue
            ver = item.get("version")
            if isinstance(ver, str):
                out[ver] = dict(item)

    fallback_ver = entry.get("version")
    if isinstance(fallback_ver, str) and fallback_ver.strip():
        meta = {"repo": entry.get("repo", ""), "checksum": entry.get("checksum", "")}
        out.setdefault(fallback_ver.strip(), meta)
    return out


def _resolve_from_registry(pkg: str, constraint: str, registry: dict[str, dict]) -> tuple[str, dict[str, Any]]:
    entry = registry.get(pkg)
    if not isinstance(entry, dict):
        raise ValueError(_diag(f"package `{pkg}` not found in registry; try `astpm search {pkg}`"))

    versions = _registry_versions(entry)
    if not versions:
        raise ValueError(_diag(f"package `{pkg}` has no versions configured in registry"))

    candidates = [v for v in versions.keys() if _matches_semver_constraint(v, constraint)]
    if not candidates:
        raise ValueError(_diag(f"no version of `{pkg}` satisfies `{constraint}`"))

    version = sorted(candidates, key=_semver_sort_key, reverse=True)[0]
    meta = versions[version]
    repo = str(meta.get("repo", entry.get("repo", ""))).strip()
    if not repo:
        raise ValueError(_diag(f"package `{pkg}` version `{version}` has no repository configured"))
    checksum = str(meta.get("checksum", "")).strip()
    return version, {"repo": repo, "checksum": checksum}


def _resolve_from_registry_many(pkg: str, constraints: list[str], registry: dict[str, dict]) -> tuple[str, dict[str, Any]]:
    entry = registry.get(pkg)
    if not isinstance(entry, dict):
        raise ValueError(_diag(f"package `{pkg}` not found in registry; try `astpm search {pkg}`"))

    versions = _registry_versions(entry)
    if not versions:
        raise ValueError(_diag(f"package `{pkg}` has no versions configured in registry"))

    filtered: list[str] = []
    for ver in versions.keys():
        if all(_matches_semver_constraint(ver, c) for c in constraints):
            filtered.append(ver)

    if not filtered:
        joined = " & ".join(constraints) if constraints else "*"
        available = sorted(versions.keys(), key=_semver_sort_key, reverse=True)[:5]
        avail_str = ", ".join(available) if available else "(none)"
        detail_parts = []
        for c in constraints:
            matching = [v for v in versions.keys() if _matches_semver_constraint(v, c)]
            if matching:
                detail_parts.append(f"  constraint `{c}` matches: {', '.join(sorted(matching, key=_semver_sort_key, reverse=True)[:3])}")
            else:
                detail_parts.append(f"  constraint `{c}` matches no available versions")
        detail = "\n".join(detail_parts)
        raise ValueError(
            _diag(
                f"no version of `{pkg}` satisfies all constraints `{joined}`\n"
                f"  available versions: {avail_str}\n"
                f"  per-constraint breakdown:\n{detail}\n"
                f"  hint: relax one of the conflicting constraints or pin a compatible version"
            )
        )

    version = sorted(filtered, key=_semver_sort_key, reverse=True)[0]
    meta = versions[version]
    repo = str(meta.get("repo", entry.get("repo", ""))).strip()
    if not repo:
        raise ValueError(_diag(f"package `{pkg}` version `{version}` has no repository configured"))
    checksum = str(meta.get("checksum", "")).strip()
    return version, {"repo": repo, "checksum": checksum}


def _read_lock_data() -> dict:
    if not REG.exists():
        return {}
    try:
        raw = json.loads(REG.read_text())
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _locked_version(name: str) -> str | None:
    raw = _read_lock_data()
    if "packages" in raw and isinstance(raw.get("packages"), dict):
        entry = raw["packages"].get(name)
        if isinstance(entry, dict):
            ver = entry.get("version")
            if isinstance(ver, str) and ver.strip():
                return ver.strip()
    legacy = raw.get(name)
    if isinstance(legacy, str) and legacy.strip():
        return legacy.strip()
    return None


def _dir_digest(path: Path) -> str:
    h = hashlib.sha256()
    for fp in sorted([p for p in path.rglob("*") if p.is_file()]):
        rel = fp.relative_to(path).as_posix().encode("utf-8")
        h.update(rel)
        h.update(b"\0")
        h.update(fp.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def _fetch_registry() -> dict[str, dict]:
    import os

    explicit_path = os.environ.get("ASTRA_REGISTRY_PATH")
    if explicit_path:
        return json.loads(Path(explicit_path).read_text())

    url = os.environ.get("ASTRA_REGISTRY_URL", _DEFAULT_REGISTRY_URL)
    try:
        with urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            cache = _registry_cache_path()
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(data, indent=2, sort_keys=True))
            return data
    except Exception:
        cache = _registry_cache_path()
        if cache.exists():
            return json.loads(cache.read_text())
        local = _REPO_ROOT / "registry" / "packages.json"
        if local.exists():
            return json.loads(local.read_text())
        raise ValueError(_diag("failed to fetch package registry"))


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


def _package_manifest_deps(data: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(data, dict):
        return out

    deps = data.get("dependencies")
    if isinstance(deps, dict):
        for k, v in deps.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v.strip()

    deps_legacy = data.get("deps")
    if isinstance(deps_legacy, dict):
        for k, v in deps_legacy.items():
            if isinstance(k, str) and isinstance(v, str):
                out[k] = v.strip()

    return out


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
    resolved: dict[str, dict[str, str]] = {}
    registry: dict[str, dict] = {}
    try:
        registry = _fetch_registry()
    except Exception:
        registry = {}

    constraints: dict[str, list[str]] = {}
    for name, constraint in resolve(data).items():
        c = constraint.strip() or "*"
        constraints.setdefault(name, []).append(c)

    queue = list(sorted(constraints.keys()))
    seen: set[str] = set()

    while queue:
        name = queue.pop(0)
        reqs = constraints.get(name, []) or ["*"]
        if name in seen and name in resolved:
            continue

        ver = ""
        source = ""
        checksum = ""

        if registry:
            try:
                ver, meta = _resolve_from_registry_many(name, reqs, registry)
                source = str(meta.get("repo", "")).strip()
                checksum = str(meta.get("checksum", "")).strip()
            except Exception:
                ver = ""

        if not ver:
            # Offline/legacy fallback keeps deterministic shape for direct constraints.
            if len(reqs) == 1 and _is_semver(reqs[0]):
                ver = reqs[0]
            else:
                locked = _locked_version(name)
                if locked and all(_matches_semver_constraint(locked, r) for r in reqs):
                    ver = locked
                else:
                    ver = reqs[0]

        pkg_dir: Path | None = None
        if source and ver:
            try:
                pkg_dir = _ensure_package_installed(name, ver, source)
            except Exception:
                pkg_dir = None

        if checksum == "" and pkg_dir is not None and pkg_dir.exists():
            checksum = f"sha256:{_dir_digest(pkg_dir)}"

        constraint_joined = " & ".join(reqs) if len(reqs) > 1 else reqs[0]
        resolved[name] = {
            "version": ver,
            "constraint": constraint_joined,
            "source": source,
            "checksum": checksum,
        }
        seen.add(name)

        if pkg_dir is None or not pkg_dir.exists():
            continue

        pkg_manifest = _load_package_manifest(pkg_dir)
        subdeps = _package_manifest_deps(pkg_manifest)
        for dep_name, dep_constraint in sorted(subdeps.items()):
            dc = dep_constraint.strip() or "*"
            existing = constraints.setdefault(dep_name, [])
            if dc not in existing:
                existing.append(dc)
            if dep_name not in seen and dep_name not in queue:
                queue.append(dep_name)

    payload = {"version": _LOCK_SCHEMA_VERSION, "packages": resolved}
    REG.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _cmd_init(name: str) -> None:
    data = {"name": name, "deps": {}, "project_style": False}
    _write_manifest(data)
    print("initialized")


def _cmd_new(name: str) -> None:
    root = Path(name)
    if root.exists():
        raise ValueError(_diag(f"destination `{name}` already exists"))

    (root / "src").mkdir(parents=True)
    (root / "Astra.toml").write_text(
        "[project]\n"
        f'name = "{name}"\n'
        'version = "0.1.0"\n'
        'entry = "src/main.astra"\n'
        "\n"
        "[dependencies]\n"
    )
    (root / "src" / "main.astra").write_text(
        "fn main() Int{\n"
        '    print("hello from astra");\n'
        "    return 0;\n"
        "}\n"
    )
    print(f"created project `{name}`")
    print(f"  cd {name}")
    print("  astra build src/main.astra -o build/app.py --target py")


def _cmd_add(pkg: str, ver: str | None) -> None:
    data = _load_manifest()
    if ver is not None:
        # Backward-compatible mode: explicit spec (exact version or range) provided.
        data["deps"][pkg] = ver.strip()
        _write_manifest(data)
        _write_lock(data["deps"])
        print("added")
        return

    registry = _fetch_registry()
    version, meta = _resolve_from_registry(pkg, "*", registry)
    repo = str(meta.get("repo", "")).strip()
    checksum = str(meta.get("checksum", "")).strip()
    pkg_dir = _ensure_package_installed(pkg, version, repo)
    pkg_manifest = _load_package_manifest(pkg_dir)
    _maybe_run_install_hint(pkg, pkg_manifest)

    data["deps"][pkg] = version
    _write_manifest(data)
    _write_lock(data["deps"])
    csum = f" ({checksum})" if checksum else ""
    print(f"✓ Added {pkg} {version}{csum}")
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
        ver = str(meta.get("version", "")).strip()
        versions = _registry_versions(meta)
        if versions:
            ver = sorted(versions.keys(), key=_semver_sort_key, reverse=True)[0]
        rows.append((name, ver, desc))

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
    for name in sorted(data["deps"].keys()):
        constraint = str(data["deps"].get(name, "")).strip() or "*"
        try:
            latest, meta = _resolve_from_registry(name, constraint, registry)
        except Exception:
            continue
        repo = str(meta.get("repo", "")).strip()
        if not repo:
            continue
        current = _locked_version(name) or ""
        if current and _cmp_semver(current, latest) >= 0:
            continue
        _ensure_package_installed(name, latest, repo)
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


def _cmd_verify() -> None:
    data = _read_lock_data()
    packages = data.get("packages")
    if not isinstance(packages, dict):
        print("no lock metadata to verify")
        return

    checked = 0
    for name, meta in sorted(packages.items()):
        if not isinstance(meta, dict):
            continue
        version = str(meta.get("version", "")).strip()
        checksum = str(meta.get("checksum", "")).strip()
        if not version or not checksum.startswith("sha256:"):
            continue

        pkg_dir = _package_home() / name / version
        if not pkg_dir.exists():
            raise ValueError(_diag(f"package `{name}` ({version}) not installed in package cache"))

        expected = checksum[len("sha256:") :].strip()
        actual = _dir_digest(pkg_dir)
        if expected and actual != expected:
            raise ValueError(
                _diag(f"integrity mismatch for `{name}` ({version}): expected sha256:{expected}, got sha256:{actual}")
            )
        checked += 1

    print(f"verified {checked} package(s)")


def main(argv=None):
    p = argparse.ArgumentParser()
    sp = p.add_subparsers(dest="cmd", required=True)

    i = sp.add_parser("init")
    i.add_argument("name")

    n = sp.add_parser("new")
    n.add_argument("name")

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
    sp.add_parser("verify")

    ns = p.parse_args(argv)

    if ns.cmd == "init":
        _cmd_init(ns.name)
        return
    if ns.cmd == "new":
        _cmd_new(ns.name)
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
    if ns.cmd == "verify":
        _cmd_verify()
        return


if __name__ == "__main__":
    main()
