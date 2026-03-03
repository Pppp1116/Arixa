from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Any, Set
from dataclasses import dataclass

from astra.ast import ImportDecl, Program, FnDecl, ExternFnDecl, StructDecl, EnumDecl, TypeAliasDecl
from astra.parser import parse

_MANIFEST = "Astra.toml"
_STDLIB_ENV = "ASTRA_STDLIB_PATH"
_RUNTIME_ENV = "ASTRA_RUNTIME_C_PATH"
_PACKAGE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PACKAGE_ROOT.parent


class ModuleResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class ModuleSymbols:
    """Symbols exported by a module"""
    functions: Dict[str, FnDecl | ExternFnDecl]
    structs: Dict[str, StructDecl]
    enums: Dict[str, EnumDecl]
    type_aliases: Dict[str, TypeAliasDecl]
    pub_symbols: Set[str]  # Names of public symbols
    
    def get_all_symbols(self) -> Dict[str, Any]:
        """Get all symbols (public and private)"""
        all_symbols = {}
        all_symbols.update(self.functions)
        all_symbols.update(self.structs)
        all_symbols.update(self.enums)
        all_symbols.update(self.type_aliases)
        return all_symbols
    
    def get_public_symbols(self) -> Dict[str, Any]:
        """Get only public symbols"""
        public_symbols = {}
        for name in self.pub_symbols:
            if name in self.functions:
                public_symbols[name] = self.functions[name]
            elif name in self.structs:
                public_symbols[name] = self.structs[name]
            elif name in self.enums:
                public_symbols[name] = self.enums[name]
            elif name in self.type_aliases:
                public_symbols[name] = self.type_aliases[name]
        return public_symbols


# Cache for loaded module symbols to avoid re-parsing
_module_symbol_cache: Dict[Path, ModuleSymbols] = {}


def import_label(decl: ImportDecl) -> str:
    if decl.source is not None:
        return f'"{decl.source}"'
    return ".".join(decl.path)


def find_project_root(filename: str) -> Path | None:
    if filename == "<input>":
        return None
    start = Path(filename).resolve()
    cur = start if start.is_dir() else start.parent
    for parent in (cur, *cur.parents):
        if (parent / _MANIFEST).exists():
            return parent
    return None


def stdlib_root_path() -> Path | None:
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


def load_module_symbols(module_path: Path) -> ModuleSymbols:
    """Load and extract symbols from a module file"""
    # Check cache first
    if module_path in _module_symbol_cache:
        return _module_symbol_cache[module_path]
    
    if not module_path.exists():
        raise ModuleResolutionError(f"Module file not found: {module_path}")
    
    try:
        # Parse the module
        source = module_path.read_text()
        program = parse(source, filename=str(module_path))
        
        # Extract symbols
        functions: Dict[str, FnDecl | ExternFnDecl] = {}
        structs: Dict[str, StructDecl] = {}
        enums: Dict[str, EnumDecl] = {}
        type_aliases: Dict[str, TypeAliasDecl] = {}
        pub_symbols: Set[str] = set()
        
        for item in program.items:
            if isinstance(item, (FnDecl, ExternFnDecl)):
                functions[item.name] = item
                if item.pub:
                    pub_symbols.add(item.name)
            elif isinstance(item, StructDecl):
                structs[item.name] = item
                if item.pub:
                    pub_symbols.add(item.name)
            elif isinstance(item, EnumDecl):
                enums[item.name] = item
                if item.pub:
                    pub_symbols.add(item.name)
            elif isinstance(item, TypeAliasDecl):
                type_aliases[item.name] = item
                # Type aliases are always public in current implementation
                pub_symbols.add(item.name)
        
        symbols = ModuleSymbols(
            functions=functions,
            structs=structs,
            enums=enums,
            type_aliases=type_aliases,
            pub_symbols=frozenset(pub_symbols)
        )
        
        # Cache the results
        _module_symbol_cache[module_path] = symbols
        return symbols
        
    except Exception as e:
        raise ModuleResolutionError(f"Failed to load symbols from {module_path}: {e}")


def get_imported_symbols(import_decl: ImportDecl, from_filename: str) -> Dict[str, Any]:
    """Get symbols from an imported module"""
    try:
        module_path = resolve_import_path(import_decl, from_filename)
        symbols = load_module_symbols(module_path)
        
        # Return only public symbols
        return symbols.get_public_symbols()
        
    except ModuleResolutionError:
        # If we can't resolve the import, return empty dict
        # This allows the compiler to continue with other errors
        return {}


def clear_module_cache() -> None:
    """Clear the module symbol cache (useful for testing or hot reload)"""
    global _module_symbol_cache
    _module_symbol_cache.clear()
