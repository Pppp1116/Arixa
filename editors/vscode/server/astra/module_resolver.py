"""Import resolution logic for stdlib, package, and file-path modules."""

from __future__ import annotations

import json
import os
from pathlib import Path
try:
    import tomllib
except Exception:  # pragma: no cover - only for older Python fallback
    import tomli as tomllib

from astra.ast import ImportDecl

_MANIFEST = "Astra.toml"
_LOCKFILE = "Astra.lock"
_STDLIB_ENV = "ASTRA_STDLIB_PATH"
_RUNTIME_ENV = "ASTRA_RUNTIME_C_PATH"
_PKG_HOME_ENV = "ARIXA_PKG_HOME"
_PACKAGE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_ROOT.parent


class ModuleResolutionError(ValueError):
    """Error type raised by the module_resolver subsystem.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pass


def import_label(decl: ImportDecl) -> str:
    """Execute the `import_label` routine.
    
    Parameters:
        decl: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    if decl.source is not None:
        return f'"{decl.source}"'
    return ".".join(decl.path)


def find_project_root(filename: str) -> Path | None:
    """Find and return the result for `find_project_root`.
    
    Parameters:
        filename: Filename context used for diagnostics or path resolution.
    
    Returns:
        Value described by the function return annotation.
    """
    if filename == "<input>":
        return None
    start = Path(filename).resolve()
    cur = start if start.is_dir() else start.parent
    for parent in (cur, *cur.parents):
        if (parent / _MANIFEST).exists():
            return parent
    return None


def stdlib_root_path() -> Path | None:
    """Execute the `stdlib_root_path` routine.
    
    Parameters:
        none
    
    Returns:
        Value described by the function return annotation.
    """
    candidates: list[Path] = []
    env = os.environ.get(_STDLIB_ENV)
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(_REPO_ROOT / "stdlib")
    candidates.append(_PACKAGE_ROOT / "stdlib")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def runtime_source_path() -> Path | None:
    """Execute the `runtime_source_path` routine.
    
    Parameters:
        none
    
    Returns:
        Value described by the function return annotation.
    """
    candidates: list[Path] = []
    env = os.environ.get(_RUNTIME_ENV)
    if env:
        candidates.append(Path(env).expanduser())
    candidates.append(_REPO_ROOT / "runtime" / "llvm_runtime.c")
    candidates.append(_PACKAGE_ROOT / "assets" / "runtime" / "llvm_runtime.c")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def package_cache_root() -> Path:
    env = os.environ.get(_PKG_HOME_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".arixa" / "packages").resolve()


def resolve_import_path(decl: ImportDecl, from_filename: str) -> Path:
    """Resolve an import declaration into an absolute filesystem path.
    
    Parameters:
        decl: Input value used by this routine.
        from_filename: Filename context used for diagnostics or path resolution.
    
    Returns:
        Value described by the function return annotation.
    """
    label = import_label(decl)
    if decl.source is not None:
        target = _resolve_string_import(decl.source, from_filename)
    else:
        target = _resolve_module_import(decl.path, from_filename, label)
    if target.suffix == "":
        target = target.with_suffix(".arixa")
    target = target.resolve()
    if not target.exists():
        raise ModuleResolutionError(f"cannot resolve import {label}")
    return target


def _resolve_string_import(source: str, from_filename: str) -> Path:
    if not source:
        raise ModuleResolutionError('cannot resolve import ""')
    rel = Path(source).expanduser()
    if rel.is_absolute():
        return rel
    importer_dir = Path.cwd() if from_filename == "<input>" else Path(from_filename).resolve().parent
    # Relative file/module import from the importer directory.
    rel_candidates: list[Path] = [importer_dir / rel]
    if rel.suffix == "":
        rel_candidates.append((importer_dir / rel).with_suffix(".arixa"))
        rel_candidates.append(importer_dir / rel / "mod.arixa")
    for cand in rel_candidates:
        if cand.exists():
            return cand

    # Import from stdlib bindings and root stdlib modules.
    stdlib_root = stdlib_root_path()
    if stdlib_root is not None and rel.suffix == "":
        binding = stdlib_root / "bindings" / f"{source}.arixa"
        if binding.exists():
            return binding
        std_mod = stdlib_root / f"{source}.arixa"
        if std_mod.exists():
            return std_mod

    # Import from package cache (~/.arixa/packages/<name>/<version>/...).
    if rel.suffix == "":
        project_root = find_project_root(from_filename) if from_filename != "<input>" else find_project_root(str(Path.cwd()))
        source_norm = source.replace("\\", "/")
        pkg_name = source_norm.split("/", 1)[0]
        subpath = source_norm.split("/", 1)[1] if "/" in source_norm else ""
        version = _dependency_version(project_root, pkg_name)
        root = package_cache_root()
        if version:
            by_ver = root / pkg_name / version
            cand = _package_module_candidate(by_ver, pkg_name, subpath)
            if cand is not None:
                return cand
        pkg_dir = root / pkg_name
        if pkg_dir.is_dir():
            versions = sorted([p for p in pkg_dir.iterdir() if p.is_dir()], reverse=True)
            for ver_dir in versions:
                cand = _package_module_candidate(ver_dir, pkg_name, subpath)
                if cand is not None:
                    return cand
    if from_filename == "<input>":
        return Path.cwd() / rel
    return Path(from_filename).resolve().parent / rel


def _package_module_candidate(pkg_version_dir: Path, name: str, subpath: str = "") -> Path | None:
    if subpath:
        cands = [
            pkg_version_dir / f"{subpath}.arixa",
            pkg_version_dir / subpath / "mod.arixa",
            pkg_version_dir / "bindings" / f"{subpath}.arixa",
            pkg_version_dir / name / f"{subpath}.arixa",
            pkg_version_dir / name / subpath / "mod.arixa",
        ]
    else:
        cands = [
            pkg_version_dir / f"{name}.arixa",
            pkg_version_dir / "bindings" / f"{name}.arixa",
            pkg_version_dir / name / "mod.arixa",
            pkg_version_dir / "mod.arixa",
        ]
    for cand in cands:
        if cand.exists():
            return cand
    return None


def _dependency_version(project_root: Path | None, name: str) -> str | None:
    if project_root is None:
        return None
    lock = project_root / _LOCKFILE
    if lock.exists():
        try:
            data = json.loads(lock.read_text())
        except Exception:
            data = None
        if isinstance(data, dict):
            packages = data.get("packages")
            if isinstance(packages, dict):
                entry = packages.get(name)
                if isinstance(entry, dict):
                    ver = entry.get("version")
                    if isinstance(ver, str) and ver.strip():
                        return ver.strip()
            legacy = data.get(name)
            if isinstance(legacy, str) and legacy.strip():
                return legacy.strip()

    manifest = project_root / _MANIFEST
    if not manifest.exists():
        return None
    try:
        data = tomllib.loads(manifest.read_text())
    except Exception:
        return None

    deps = data.get("dependencies")
    if isinstance(deps, dict):
        val = deps.get(name)
        if isinstance(val, str) and val.strip():
            return val.strip()
    deps_legacy = data.get("deps")
    if isinstance(deps_legacy, dict):
        val = deps_legacy.get(name)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return None


def _resolve_module_import(path: list[str], from_filename: str, label: str) -> Path:
    if not path:
        raise ModuleResolutionError("empty import path")
    if path[0] in {"std", "stdlib"}:
        stdlib_root = stdlib_root_path()
        if stdlib_root is None:
            raise ModuleResolutionError(f"cannot resolve import {label} (stdlib not found)")
        if len(path) == 1:
            raise ModuleResolutionError(f"cannot resolve import {label}")
        return stdlib_root.joinpath(*path[1:])
    rel = Path(*path)
    package_root = find_project_root(from_filename)
    if package_root is not None:
        return package_root / rel
    if from_filename == "<input>":
        return Path.cwd() / rel
    return Path(from_filename).resolve().parent / rel
