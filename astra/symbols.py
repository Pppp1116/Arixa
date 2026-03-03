"""
Thread-safe symbol table management for parallel ASTRA compilation.

Provides a frozen global symbol table pattern for safe parallel access
during semantic analysis.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set, Tuple
from pathlib import Path
from collections import defaultdict

from astra.ast import (
    FnDecl, ExternFnDecl, StructDecl, EnumDecl, 
    TypeAliasDecl, ImportDecl, Program
)
from astra.module_resolver import resolve_import_path, ModuleResolutionError


@dataclass(frozen=True)
class SymbolInfo:
    """Immutable symbol information for thread-safe access"""
    name: str
    symbol_type: str  # "fn", "struct", "enum", "type_alias", "extern_fn"
    decl: Any  # The actual declaration
    file_path: str
    span_info: Tuple[int, int, int] = field(default_factory=lambda: (0, 0, 0))  # line, col, pos


@dataclass(frozen=True)
class GlobalSymbolTable:
    """Immutable global symbol table for parallel access"""
    functions: Dict[str, List[SymbolInfo]] = field(default_factory=dict)
    structs: Dict[str, SymbolInfo] = field(default_factory=dict)
    enums: Dict[str, SymbolInfo] = field(default_factory=dict)
    type_aliases: Dict[str, SymbolInfo] = field(default_factory=dict)
    extern_functions: Dict[str, List[SymbolInfo]] = field(default_factory=dict)
    global_scope: Dict[str, str] = field(default_factory=dict)
    
    def get_function_overloads(self, name: str) -> List[SymbolInfo]:
        """Get all overloads for a function name"""
        return self.functions.get(name, [])
    
    def get_struct(self, name: str) -> Optional[SymbolInfo]:
        """Get struct declaration"""
        return self.structs.get(name)
    
    def get_enum(self, name: str) -> Optional[SymbolInfo]:
        """Get enum declaration"""
        return self.enums.get(name)
    
    def get_type_alias(self, name: str) -> Optional[SymbolInfo]:
        """Get type alias declaration"""
        return self.type_aliases.get(name)
    
    def get_extern_function(self, name: str) -> List[SymbolInfo]:
        """Get extern function overloads"""
        return self.extern_functions.get(name, [])
    
    def is_global_symbol(self, name: str) -> bool:
        """Check if name is in global scope"""
        return name in self.global_scope


class MutableSymbolTable:
    """Mutable symbol table builder (single-threaded construction phase)"""
    
    def __init__(self):
        self.functions: Dict[str, List[SymbolInfo]] = defaultdict(list)
        self.structs: Dict[str, SymbolInfo] = {}
        self.enums: Dict[str, SymbolInfo] = {}
        self.type_aliases: Dict[str, SymbolInfo] = {}
        self.extern_functions: Dict[str, List[SymbolInfo]] = defaultdict(list)
        self.global_scope: Dict[str, str] = {}
        self._lock = threading.Lock()
    
    def add_function(self, fn_decl: FnDecl, file_path: str) -> None:
        """Add a function declaration"""
        info = SymbolInfo(
            name=fn_decl.name,
            symbol_type="fn",
            decl=fn_decl,
            file_path=file_path,
            span_info=(fn_decl.line, fn_decl.col, fn_decl.pos)
        )
        self.functions[fn_decl.name].append(info)
    
    def add_extern_function(self, extern_decl: ExternFnDecl, file_path: str) -> None:
        """Add an extern function declaration"""
        info = SymbolInfo(
            name=extern_decl.name,
            symbol_type="extern_fn",
            decl=extern_decl,
            file_path=file_path,
            span_info=(extern_decl.line, extern_decl.col, extern_decl.pos)
        )
        self.extern_functions[extern_decl.name].append(info)
    
    def add_struct(self, struct_decl: StructDecl, file_path: str) -> None:
        """Add a struct declaration"""
        info = SymbolInfo(
            name=struct_decl.name,
            symbol_type="struct",
            decl=struct_decl,
            file_path=file_path,
            span_info=(struct_decl.line, struct_decl.col, struct_decl.pos)
        )
        self.structs[struct_decl.name] = info
    
    def add_enum(self, enum_decl: EnumDecl, file_path: str) -> None:
        """Add an enum declaration"""
        info = SymbolInfo(
            name=enum_decl.name,
            symbol_type="enum",
            decl=enum_decl,
            file_path=file_path,
            span_info=(enum_decl.line, enum_decl.col, enum_decl.pos)
        )
        self.enums[enum_decl.name] = info
    
    def add_type_alias(self, alias_decl: TypeAliasDecl, file_path: str) -> None:
        """Add a type alias declaration"""
        info = SymbolInfo(
            name=alias_decl.name,
            symbol_type="type_alias",
            decl=alias_decl,
            file_path=file_path,
            span_info=(alias_decl.line, alias_decl.col, alias_decl.pos)
        )
        self.type_aliases[alias_decl.name] = info
    
    def add_import_alias(self, alias: str, import_info: str) -> None:
        """Add import alias to global scope"""
        self.global_scope[alias] = import_info
    
    def freeze(self) -> GlobalSymbolTable:
        """Convert to immutable global symbol table"""
        return GlobalSymbolTable(
            functions=dict(self.functions),
            structs=dict(self.structs),
            enums=dict(self.enums),
            type_aliases=dict(self.type_aliases),
            extern_functions=dict(self.extern_functions),
            global_scope=dict(self.global_scope)
        )


class SymbolTableBuilder:
    """Builds global symbol table from multiple AST programs"""
    
    def __init__(self):
        self.mutable_table = MutableSymbolTable()
        self.processed_files: Set[str] = set()
    
    def add_program(self, program: Program, file_path: str) -> None:
        """Add symbols from a program to the table"""
        if file_path in self.processed_files:
            return
        
        for item in program.items:
            if isinstance(item, FnDecl):
                self.mutable_table.add_function(item, file_path)
            elif isinstance(item, ExternFnDecl):
                self.mutable_table.add_extern_function(item, file_path)
            elif isinstance(item, StructDecl):
                self.mutable_table.add_struct(item, file_path)
            elif isinstance(item, EnumDecl):
                self.mutable_table.add_enum(item, file_path)
            elif isinstance(item, TypeAliasDecl):
                self.mutable_table.add_type_alias(item, file_path)
            elif isinstance(item, ImportDecl):
                # Handle import aliases
                if item.alias:
                    import_info = f"module:{item.path[-1]}" if item.path else f"file:{item.source}"
                    self.mutable_table.add_import_alias(item.alias, import_info)
        
        self.processed_files.add(file_path)
    
    def build(self) -> GlobalSymbolTable:
        """Build the frozen global symbol table"""
        return self.mutable_table.freeze()


def build_global_symbol_table(asts: Dict[Path, Any]) -> GlobalSymbolTable:
    """
    Build a global symbol table from multiple parsed ASTs.
    
    This function is called sequentially before parallel semantic analysis.
    """
    from astra.profiler import profiler
    
    with profiler.section("build_symbol_table"):
        builder = SymbolTableBuilder()
        
        # Add all programs to the builder
        for file_path, ast in asts.items():
            if hasattr(ast, 'items'):
                builder.add_program(ast, str(file_path))
            else:
                # Handle case where AST might be just a list of items
                if isinstance(ast, list):
                    program = Program(items=ast)
                    builder.add_program(program, str(file_path))
        
        return builder.build()


def validate_symbol_consistency(table: GlobalSymbolTable) -> List[str]:
    """
    Validate the global symbol table for consistency issues.
    Returns a list of error messages.
    """
    errors = []
    
    # Check for function overload conflicts
    for name, overloads in table.functions.items():
        if len(overloads) > 1:
            # Check for duplicate signatures (would cause ambiguity)
            signatures = set()
            for info in overloads:
                fn = info.decl
                sig = (tuple(p[1] for p in fn.params), fn.ret)
                if sig in signatures:
                    errors.append(
                        f"Duplicate function signature for {name}({', '.join(sig[0])}) -> {sig[1]} "
                        f"in {info.file_path}:{info.span_info[0]}"
                    )
                signatures.add(sig)
    
    # Check for name conflicts between different symbol types
    all_names = set()
    for name in table.structs:
        if name in all_names:
            errors.append(f"Name conflict: struct {name} conflicts with another symbol")
        all_names.add(name)
    
    for name in table.enums:
        if name in all_names:
            errors.append(f"Name conflict: enum {name} conflicts with another symbol")
        all_names.add(name)
    
    for name in table.type_aliases:
        if name in all_names:
            errors.append(f"Name conflict: type alias {name} conflicts with another symbol")
        all_names.add(name)
    
    return errors
