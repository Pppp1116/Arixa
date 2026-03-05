"""Import resolution logic for stdlib, package, and file-path modules."""

from __future__ import annotations

import os
from pathlib import Path

from astra.ast import ImportDecl

_MANIFEST = "Astra.toml"
_STDLIB_ENV = "ASTRA_STDLIB_PATH"
_RUNTIME_ENV = "ASTRA_RUNTIME_C_PATH"
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
        target = target.with_suffix(".astra")
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
    if from_filename == "<input>":
        return Path.cwd() / rel
    return Path(from_filename).resolve().parent / rel


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
