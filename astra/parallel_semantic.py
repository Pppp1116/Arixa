"""
Parallel semantic analysis for ASTRA compiler.

Performs type checking and semantic validation of function bodies
in parallel using a frozen global symbol table.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

from astra.ast import FnDecl, ExternFnDecl, Program
from astra.symbols import GlobalSymbolTable, SymbolInfo
from astra.parallel import ParallelExecutor, WorkItem, DeterministicMerge
from astra.profiler import profiler
from astra.semantic import SemanticError, _analyze_fn


@dataclass
class SemanticWorkItem:
    """A function to analyze in parallel"""
    fn_decl: FnDecl
    file_path: str
    fn_groups: Dict[str, List[FnDecl | ExternFnDecl]]
    structs: Dict[str, Any]
    enums: Dict[str, Any]
    global_scope: Dict[str, str]


class ThreadLocalDiagnostics:
    """Thread-local diagnostic collection"""
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def add_error(self, error: str) -> None:
        self.errors.append(error)
    
    def add_warning(self, warning: str) -> None:
        self.warnings.append(warning)


def analyze_function_parallel(work_item: SemanticWorkItem) -> ThreadLocalDiagnostics:
    """
    Analyze a single function in parallel.
    Returns thread-local diagnostics.
    """
    diagnostics = ThreadLocalDiagnostics()
    
    try:
        _analyze_fn(
            work_item.fn_decl,
            work_item.fn_groups,
            work_item.structs,
            work_item.enums,
            work_item.file_path,
            work_item.global_scope
        )
    except SemanticError as e:
        diagnostics.add_error(str(e))
    except Exception as e:
        diagnostics.add_error(f"INTERNAL {work_item.file_path}:{work_item.fn_decl.line}:{work_item.fn_decl.col}: {e}")
    
    return diagnostics


def prepare_parallel_work_items(
    program: Program, 
    symbol_table: GlobalSymbolTable,
    file_path: str
) -> List[SemanticWorkItem]:
    """
    Prepare work items for parallel semantic analysis.
    
    This extracts all the necessary context for each function
    so it can be analyzed independently.
    """
    work_items = []
    
    # Build function groups from symbol table
    fn_groups: Dict[str, List[FnDecl | ExternFnDecl]] = {}
    for name, overloads in symbol_table.functions.items():
        fn_groups[name] = [info.decl for info in overloads]
    
    for name, overloads in symbol_table.extern_functions.items():
        if name not in fn_groups:
            fn_groups[name] = []
        fn_groups[name].extend([info.decl for info in overloads])
    
    # Build structs and enums from symbol table
    structs: Dict[str, Any] = {}
    for name, info in symbol_table.structs.items():
        structs[name] = info.decl
    
    enums: Dict[str, Any] = {}
    for name, info in symbol_table.enums.items():
        enums[name] = info.decl
    
    # Create work items for each function
    for item in program.items:
        if isinstance(item, FnDecl):
            work_item = SemanticWorkItem(
                fn_decl=item,
                file_path=file_path,
                fn_groups=fn_groups,
                structs=structs,
                enums=enums,
                global_scope=symbol_table.global_scope
            )
            work_items.append(work_item)
    
    return work_items


def analyze_program_parallel(
    program: Program,
    symbol_table: GlobalSymbolTable,
    file_path: str,
    freestanding: bool = False
) -> None:
    """
    Analyze a program's functions in parallel.
    
    Uses the frozen symbol table for safe parallel access.
    Raises SemanticError if any issues are found.
    """
    from astra.semantic import _FREESTANDING_MODE_STACK
    
    _FREESTANDING_MODE_STACK.append(freestanding)
    
    try:
        # Prepare work items
        work_items = prepare_parallel_work_items(program, symbol_table, file_path)
        
        if not work_items:
            return  # No functions to analyze
        
        # Analyze functions in parallel
        diagnostics_lists = []
        
        if len(work_items) == 1:
            # Sequential analysis for single function
            with profiler.section("semantic_sequential"):
                diagnostics = analyze_function_parallel(work_items[0])
                diagnostics_lists.append([diagnostics])
        else:
            # Parallel analysis for multiple functions
            with profiler.section("semantic_parallel"):
                with ParallelExecutor() as executor:
                    # Submit all work
                    futures = []
                    for i, work_item in enumerate(work_items):
                        work = WorkItem(
                            id=f"analyze_fn_{i}",
                            fn=lambda wi=work_item: analyze_function_parallel(wi)
                        )
                        future = executor.submit_work(work)
                        futures.append((work.id, future))
                    
                    # Collect results
                    for work_id, future in futures:
                        try:
                            diagnostics = executor.wait_for(work_id)
                            diagnostics_lists.append([diagnostics])
                        except Exception as e:
                            # Create error diagnostics
                            error_diag = ThreadLocalDiagnostics()
                            error_diag.add_error(f"INTERNAL: Failed to analyze function: {e}")
                            diagnostics_lists.append([error_diag])
        
        # Merge diagnostics deterministically
        all_errors = []
        all_warnings = []
        
        for diag_list in diagnostics_lists:
            for diagnostics in diag_list:
                all_errors.extend(diagnostics.errors)
                all_warnings.extend(diagnostics.warnings)
        
        # Sort deterministically for reproducible output
        all_errors.sort()
        all_warnings.sort()
        
        # Raise errors if any found
        if all_errors:
            raise SemanticError("\n".join(all_errors))
            
    finally:
        _FREESTANDING_MODE_STACK.pop()


def analyze_programs_parallel(
    programs: Dict[Path, Program],
    symbol_table: GlobalSymbolTable,
    freestanding: bool = False
) -> None:
    """
    Analyze multiple programs in parallel.
    
    Each program's functions are analyzed in parallel, and multiple
    programs can also be analyzed in parallel if they don't have
    interdependencies.
    """
    if len(programs) == 1:
        # Single program - use regular parallel analysis
        file_path, program = next(iter(programs.items()))
        analyze_program_parallel(program, symbol_table, str(file_path), freestanding)
        return
    
    # Multiple programs - analyze each program's functions in parallel
    program_diagnostics = {}
    
    with ParallelExecutor() as executor:
        # Submit all programs for analysis
        futures = []
        for file_path, program in programs.items():
            work = WorkItem(
                id=f"analyze_program_{file_path.name}",
                fn=lambda fp=file_path, prog=program: analyze_single_program_for_parallel(
                    prog, symbol_table, str(fp), freestanding
                )
            )
            future = executor.submit_work(work)
            futures.append((work.id, future))
        
        # Collect results
        for work_id, future in futures:
            try:
                diagnostics = executor.wait_for(work_id)
                program_diagnostics[work_id] = diagnostics
            except Exception as e:
                # Create error diagnostics
                error_diag = ThreadLocalDiagnostics()
                error_diag.add_error(f"INTERNAL: Failed to analyze program: {e}")
                program_diagnostics[work_id] = error_diag
    
    # Merge all diagnostics
    all_errors = []
    all_warnings = []
    
    for diagnostics in program_diagnostics.values():
        all_errors.extend(diagnostics.errors)
        all_warnings.extend(diagnostics.warnings)
    
    # Sort deterministically
    all_errors.sort()
    all_warnings.sort()
    
    # Raise errors if any found
    if all_errors:
        raise SemanticError("\n".join(all_errors))


def analyze_single_program_for_parallel(
    program: Program,
    symbol_table: GlobalSymbolTable,
    file_path: str,
    freestanding: bool
) -> ThreadLocalDiagnostics:
    """
    Analyze a single program and return diagnostics.
    Used for parallel multi-program analysis.
    """
    diagnostics = ThreadLocalDiagnostics()
    
    try:
        analyze_program_parallel(program, symbol_table, file_path, freestanding)
    except SemanticError as e:
        diagnostics.add_error(str(e))
    except Exception as e:
        diagnostics.add_error(f"INTERNAL {file_path}:1:1: {e}")
    
    return diagnostics
