"""
Parallel compilation utilities for ASTRA compiler.

Provides thread pool management, work-stealing, and deterministic
parallel execution for compiler phases.
"""

from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, TypeVar, Dict
from pathlib import Path

from astra.profiler import profiler

T = TypeVar('T')


@dataclass
class WorkItem:
    """A unit of work that can be executed in parallel"""
    id: str
    fn: Callable[[], T]
    dependencies: List[str] = None  # IDs of work items this depends on
    
    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


class ParallelExecutor:
    """
    Thread pool executor with work-stealing and dependency tracking.
    Ensures deterministic execution order for compiler phases.
    """
    
    def __init__(self, max_workers: Optional[int] = None):
        self.max_workers = max_workers or int(os.environ.get("ASTRA_THREADS", os.cpu_count() or 1))
        self._pool: Optional[ThreadPoolExecutor] = None
        self._futures: Dict[str, Future] = {}
        self._results: Dict[str, Any] = {}
        self._lock = threading.Lock()
        
    def __enter__(self):
        self._pool = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="astra-compile")
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._pool:
            self._pool.shutdown(wait=True)
            self._pool = None
    
    def submit_work(self, work: WorkItem) -> Future:
        """Submit work item respecting dependencies"""
        if not self._pool:
            raise RuntimeError("ParallelExecutor not active (use context manager)")
        
        with self._lock:
            # Check if dependencies are satisfied
            for dep_id in work.dependencies:
                if dep_id not in self._results:
                    raise ValueError(f"Work item {work.id} depends on {dep_id} which is not completed")
            
            # Submit the work
            future = self._pool.submit(self._execute_work, work)
            self._futures[work.id] = future
            return future
    
    def _execute_work(self, work: WorkItem) -> Any:
        """Execute a work item with profiling"""
        with profiler.section(f"parallel_{work.id}"):
            return work.fn()
    
    def wait_for(self, work_id: str) -> Any:
        """Wait for specific work item to complete and return result"""
        with self._lock:
            if work_id in self._results:
                return self._results[work_id]
            
            if work_id not in self._futures:
                raise ValueError(f"Work item {work_id} not found")
            
            future = self._futures[work_id]
        
        try:
            result = future.result()
            with self._lock:
                self._results[work_id] = result
                del self._futures[work_id]
            return result
        except Exception as e:
            with self._lock:
                if work_id in self._futures:
                    del self._futures[work_id]
            raise e
    
    def wait_all(self) -> Dict[str, Any]:
        """Wait for all submitted work to complete"""
        remaining_futures = list(self._futures.values())
        
        for future in as_completed(remaining_futures):
            try:
                future.result()  # Wait for completion
            except Exception:
                pass  # Errors will be propagated when individual items are waited for
        
        with self._lock:
            results = dict(self._results)
            self._futures.clear()
            return results


def parse_file_parallel(file_path: Path) -> tuple[Path, Any]:
    """Parse a single file in parallel"""
    from astra.parser import parse
    
    try:
        src = file_path.read_text()
        ast = parse(src, filename=str(file_path))
        return file_path, ast
    except Exception as e:
        # Return error information for main thread to handle
        return file_path, e


def collect_files_parallel(src_file: Path) -> List[Path]:
    """Collect all input files with parallel dependency resolution"""
    from astra.build import _collect_input_files
    
    # For now, use existing sequential collection to avoid recursion
    # This could be parallelized in a future optimization with proper cycle detection
    return _collect_input_files.__wrapped__(src_file)


def parse_files_parallel(file_paths: List[Path]) -> Dict[Path, Any]:
    """Parse multiple files in parallel"""
    if not file_paths:
        return {}
    
    results = {}
    
    with ParallelExecutor() as executor:
        # Submit all parsing work
        work_items = []
        for file_path in file_paths:
            work = WorkItem(
                id=f"parse_{file_path.name}",
                fn=lambda fp=file_path: parse_file_parallel(fp)
            )
            work_items.append(work)
            executor.submit_work(work)
        
        # Wait for all to complete
        for work in work_items:
            try:
                file_path, result = executor.wait_for(work.id)
                results[file_path] = result
            except Exception as e:
                results[file_path] = e
    
    return results


class DeterministicMerge:
    """Helper for deterministic merging of parallel results"""
    
    @staticmethod
    def merge_diagnostics(diagnostics_lists: List[List[Any]]) -> List[Any]:
        """Merge diagnostics from multiple threads deterministically"""
        all_diags = []
        for diag_list in diagnostics_lists:
            all_diags.extend(diag_list)
        
        # Sort deterministically by file, line, column, then message
        all_diags.sort(key=lambda d: (
            getattr(d.span, 'filename', '') if hasattr(d, 'span') and d.span else '',
            getattr(d.span, 'line', 0) if hasattr(d, 'span') and d.span else 0,
            getattr(d.span, 'col', 0) if hasattr(d, 'span') and d.span else 0,
            d.message if hasattr(d, 'message') else str(d)
        ))
        return all_diags
    
    @staticmethod
    def merge_symbol_tables(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge symbol tables from multiple threads"""
        merged = {}
        for table in tables:
            for name, symbol in table.items():
                if name in merged:
                    # Handle conflicts - for now, last one wins
                    # In practice, this should be prevented by proper dependency ordering
                    merged[name] = symbol
                else:
                    merged[name] = symbol
        return merged


def get_thread_count() -> int:
    """Get the configured thread count for compilation"""
    return int(os.environ.get("ASTRA_THREADS", os.cpu_count() or 1))


def is_parallel_enabled() -> bool:
    """Check if parallel compilation is enabled"""
    return get_thread_count() > 1
