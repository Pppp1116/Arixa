"""Enhanced build system with integrated optimization pipeline."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

try:
    import tomllib
except Exception:
    import tomli as tomllib

from astra import __version__ as ASTRA_VERSION
from astra.ast import (
    ArrayLit,
    AssignStmt,
    AwaitExpr,
    Binary,
    Call,
    CastExpr,
    ComptimeStmt,
    EnumDecl,
    ExternFnDecl,
    ExprStmt,
    FieldExpr,
    FnDecl,
    IfStmt,
    IndexExpr,
    LetStmt,
    MatchStmt,
    Name,
    ReturnStmt,
    StringInterpolation,
    StructDecl,
    StructLit,
    TryExpr,
    TypeAliasDecl,
    TypeAnnotated,
    Unary,
    UnsafeStmt,
    WhileStmt,
)
from astra.build import (
    _collect_input_files, _collect_imported_items, _expand_serde_derives,
    _dependency_native_link_data, _build_fingerprint, _resolve_overflow_mode,
    _load_project_manifest, _load_project_dependencies, _platform_key,
    _append_unique, _extract_link_list, _extract_pkg_config_name,
    _pkg_config_link_args, _build_native_llvm, _require_runtime_free_freestanding,
    CACHE, _REPO_ROOT, _TOOLCHAIN_STAMP
)
from astra.parser import parse
from astra.semantic import analyze
from astra.for_lowering import lower_for_loops
from astra.gpu.kernel_lowering import lower_gpu_kernels
from astra.comptime import run_comptime
from astra.codegen import to_python
from astra.optimizer.optimizer_enhanced import optimize_program_enhanced
from astra.llvm_codegen_enhanced import to_llvm_ir_enhanced


class EnhancedBuildPipeline:
    """Enhanced build pipeline with optimization support."""
    
    def __init__(self, profile: str = "debug", overflow_mode: str = "debug"):
        self.profile = profile
        self.overflow_mode = overflow_mode
    
    def build(
        self,
        src_path: str,
        out_path: str,
        target: str = "py",
        kind: str = "exe",
        emit_ir: bool = False,
        strict: bool = False,
        freestanding: bool = False,
        profile: str = "debug",
        overflow: str = "trap",
        sanitize: str | None = None,
        triple: str | None = None,
        links: list[str] | None = None,
    ) -> str:
        """Enhanced build pipeline with optimization support."""
        src_file = Path(src_path)
        overflow_mode = overflow
        digest = hashlib.sha256(src_file.read_text().encode()).hexdigest()
        cache_key = (
            f"{src_file.resolve().as_posix()}::{target}::{kind}::{int(bool(strict))}::{int(bool(freestanding))}::"
            f"{int(bool(emit_ir))}::{profile}::{overflow_mode}::{sanitize or ''}::{triple or ''}::{','.join(sorted(set(links or [])))}"
        )
        cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
        if cache.get(cache_key) == digest and Path(out_path).exists():
            return 'cached'
        
        # Enhanced compilation pipeline
        prog = self._parse_and_analyze(src_file, overflow_mode, freestanding, kind)
        prog = self._optimize_program_enhanced(prog, overflow_mode, profile)
        
        # Generate output
        if target == "py":
            self._generate_python_output(prog, out_path, freestanding, overflow_mode, kind)
        elif target in {"llvm", "native"}:
            llvm_ir = self._generate_llvm_output(prog, freestanding, overflow_mode, triple, profile, src_file)
            if emit_ir:
                self._write_ir_file(emit_ir, llvm_ir)
            if target == "llvm":
                self._write_llvm_output(out_path, llvm_ir)
            else:  # native
                self._generate_native_output(
                    llvm_ir, out_path, src_file, prog, profile, sanitize, triple,
                    freestanding, kind, links
                )
        
        # Update cache
        cache[cache_key] = digest
        CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=2))
        return 'built'
    
    def _parse_and_analyze(self, src_file: Path, overflow_mode: str, freestanding: bool, kind: str) -> Any:
        """Parse and analyze source with enhanced error handling."""
        src = src_file.read_text()
        prog = parse(src, filename=str(src_file))
        
        # Collect imported items
        imported_items = _collect_imported_items(src_file)
        if imported_items:
            self._merge_imported_items(prog, imported_items)
        
        # Expand derives
        _expand_serde_derives(prog)
        
        # Determine required entrypoint
        required_entrypoint = None if kind == "lib" else ("_start" if freestanding else "main")
        
        # Run comptime evaluation
        run_comptime(prog, filename=str(src_file), overflow_mode=overflow_mode)
        
        # Semantic analysis
        analyze(
            prog,
            filename=str(src_file),
            freestanding=freestanding,
            require_entrypoint=required_entrypoint,
        )
        
        return prog
    
    def _merge_imported_items(self, prog: Any, imported_items: list):
        """Merge imported items into program."""
        fn_keys = {
            (
                item.name,
                tuple(item.params),
                item.ret,
                bool(getattr(item, "is_variadic", False)),
                bool(getattr(item, "unsafe", False)),
                isinstance(item, ExternFnDecl),
            )
            for item in prog.items
            if isinstance(item, (FnDecl, ExternFnDecl))
        }
        named_types = {
            item.name
            for item in prog.items
            if isinstance(item, (StructDecl, EnumDecl, TypeAliasDecl))
        }
        
        for item, owner in imported_items:
            try:
                setattr(item, "_source_filename", str(owner))
            except Exception:
                pass
            
            if isinstance(item, (FnDecl, ExternFnDecl)):
                key = (
                    item.name,
                    tuple(item.params),
                    item.ret,
                    bool(getattr(item, "is_variadic", False)),
                    bool(getattr(item, "unsafe", False)),
                    isinstance(item, ExternFnDecl),
                )
                if key not in fn_keys:
                    fn_keys.add(key)
                    prog.items.append(item)
            elif isinstance(item, (StructDecl, EnumDecl, TypeAliasDecl)):
                if item.name not in named_types:
                    named_types.add(item.name)
                    prog.items.append(item)
            elif isinstance(item, LetStmt):
                if not any(isinstance(existing, LetStmt) and existing.name == item.name for existing in prog.items):
                    prog.items.append(item)
    
    def _optimize_program_enhanced(self, prog: Any, overflow_mode: str, profile: str) -> Any:
        """Apply enhanced optimization pipeline."""
        print(f"OPTIMIZE: Running enhanced optimization pipeline (profile={profile})")
        
        # Lower for loops first
        lower_for_loops(prog)
        
        # Apply enhanced optimizations
        optimized_prog = optimize_program_enhanced(prog, overflow_mode=overflow_mode, profile=profile)
        
        # Additional optimization passes for release mode
        if profile == "release":
            optimized_prog = self._apply_release_optimizations(optimized_prog)
        
        return optimized_prog
    
    def _apply_release_optimizations(self, prog: Any) -> Any:
        """Apply additional optimizations for release builds."""
        # Inline small functions
        self._inline_small_functions(prog)
        
        # Remove dead functions
        self._remove_dead_functions(prog)
        
        # Optimize memory layout
        self._optimize_memory_layout(prog)
        
        return prog
    
    def _inline_small_functions(self, prog: Any):
        """Inline small functions for better performance."""
        # This is a placeholder for function inlining
        # In a full implementation, this would analyze call graphs and inline appropriately
        pass
    
    def _remove_dead_functions(self, prog: Any):
        """Remove unused functions."""
        fn_map: dict[str, FnDecl] = {fn.name: fn for fn in prog.items if isinstance(fn, FnDecl)}
        if not fn_map:
            return

        roots: set[str] = set()
        if "main" in fn_map:
            roots.add("main")
        if "_start" in fn_map:
            roots.add("_start")
        if not roots:
            return

        reachable: set[str] = set()
        worklist = list(roots)
        while worklist:
            name = worklist.pop()
            if name in reachable:
                continue
            fn = fn_map.get(name)
            if fn is None:
                continue
            reachable.add(name)
            refs = self._referenced_functions_in_body(fn.body, set(fn_map))
            for ref in refs:
                if ref not in reachable:
                    worklist.append(ref)

        prog.items = [item for item in prog.items if not isinstance(item, FnDecl) or item.name in reachable]

    def _referenced_functions_in_body(self, body: list[Any], fn_names: set[str]) -> set[str]:
        refs: set[str] = set()
        for st in body:
            refs.update(self._referenced_functions_in_stmt(st, fn_names))
        return refs

    def _referenced_functions_in_stmt(self, stmt: Any, fn_names: set[str]) -> set[str]:
        refs: set[str] = set()
        if isinstance(stmt, LetStmt):
            refs.update(self._referenced_functions_in_expr(stmt.expr, fn_names))
        elif isinstance(stmt, AssignStmt):
            refs.update(self._referenced_functions_in_expr(stmt.target, fn_names))
            refs.update(self._referenced_functions_in_expr(stmt.expr, fn_names))
        elif isinstance(stmt, ExprStmt):
            refs.update(self._referenced_functions_in_expr(stmt.expr, fn_names))
        elif isinstance(stmt, ReturnStmt) and stmt.expr is not None:
            refs.update(self._referenced_functions_in_expr(stmt.expr, fn_names))
        elif isinstance(stmt, IfStmt):
            refs.update(self._referenced_functions_in_expr(stmt.cond, fn_names))
            refs.update(self._referenced_functions_in_body(stmt.then_body, fn_names))
            refs.update(self._referenced_functions_in_body(stmt.else_body, fn_names))
        elif isinstance(stmt, WhileStmt):
            refs.update(self._referenced_functions_in_expr(stmt.cond, fn_names))
            refs.update(self._referenced_functions_in_body(stmt.body, fn_names))
        elif isinstance(stmt, MatchStmt):
            refs.update(self._referenced_functions_in_expr(stmt.expr, fn_names))
            for pat, arm_body in stmt.arms:
                refs.update(self._referenced_functions_in_expr(pat, fn_names))
                refs.update(self._referenced_functions_in_body(arm_body, fn_names))
        elif isinstance(stmt, ComptimeStmt):
            refs.update(self._referenced_functions_in_body(stmt.body, fn_names))
        elif isinstance(stmt, UnsafeStmt):
            refs.update(self._referenced_functions_in_body(stmt.body, fn_names))
        return refs

    def _referenced_functions_in_expr(self, expr: Any, fn_names: set[str]) -> set[str]:
        refs: set[str] = set()
        if expr is None:
            return refs
        if isinstance(expr, Name):
            if expr.value in fn_names:
                refs.add(expr.value)
            return refs
        if isinstance(expr, Call):
            if isinstance(expr.fn, Name) and expr.fn.value in fn_names:
                refs.add(expr.fn.value)
            refs.update(self._referenced_functions_in_expr(expr.fn, fn_names))
            for arg in expr.args:
                refs.update(self._referenced_functions_in_expr(arg, fn_names))
            return refs
        if isinstance(expr, Unary):
            refs.update(self._referenced_functions_in_expr(expr.expr, fn_names))
            return refs
        if isinstance(expr, Binary):
            refs.update(self._referenced_functions_in_expr(expr.left, fn_names))
            refs.update(self._referenced_functions_in_expr(expr.right, fn_names))
            return refs
        if isinstance(expr, IndexExpr):
            refs.update(self._referenced_functions_in_expr(expr.obj, fn_names))
            refs.update(self._referenced_functions_in_expr(expr.index, fn_names))
            return refs
        if isinstance(expr, FieldExpr):
            refs.update(self._referenced_functions_in_expr(expr.obj, fn_names))
            return refs
        if isinstance(expr, ArrayLit):
            for el in expr.elements:
                refs.update(self._referenced_functions_in_expr(el, fn_names))
            return refs
        if isinstance(expr, StructLit):
            for _, value in expr.fields:
                refs.update(self._referenced_functions_in_expr(value, fn_names))
            return refs
        if isinstance(expr, CastExpr):
            refs.update(self._referenced_functions_in_expr(expr.expr, fn_names))
            return refs
        if isinstance(expr, TypeAnnotated):
            refs.update(self._referenced_functions_in_expr(expr.expr, fn_names))
            return refs
        if isinstance(expr, AwaitExpr):
            refs.update(self._referenced_functions_in_expr(expr.expr, fn_names))
            return refs
        if isinstance(expr, TryExpr):
            refs.update(self._referenced_functions_in_expr(expr.expr, fn_names))
            return refs
        if isinstance(expr, StringInterpolation):
            for part_expr in expr.exprs:
                refs.update(self._referenced_functions_in_expr(part_expr, fn_names))
            return refs
        return refs
    
    def _optimize_memory_layout(self, prog: Any):
        """Optimize struct layouts and memory usage."""
        # This is a placeholder for memory layout optimization
        # In a full implementation, this would reorder struct fields for better cache locality
        pass
    
    def _generate_python_output(self, prog: Any, out_path: str, freestanding: bool, overflow_mode: str, kind: str):
        """Generate optimized Python output."""
        out = to_python(prog, freestanding=freestanding, overflow_mode=overflow_mode, emit_entrypoint=(kind == "exe"))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(out)
    
    def _generate_llvm_output(self, prog: Any, freestanding: bool, overflow_mode: str, triple: str | None, profile: str, src_file: Path) -> str:
        """Generate enhanced LLVM IR with optimization attributes."""
        llvm_ir = to_llvm_ir_enhanced(
            prog,
            freestanding=freestanding,
            overflow_mode=overflow_mode,
            triple=triple,
            profile=profile,
            filename=str(src_file),
        )
        
        if freestanding:
            _require_runtime_free_freestanding(llvm_ir, src_file)
        
        return llvm_ir
    
    def _write_ir_file(self, emit_ir: str, llvm_ir: str):
        """Write LLVM IR to file."""
        p = Path(emit_ir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(llvm_ir)
    
    def _write_llvm_output(self, out_path: str, llvm_ir: str):
        """Write LLVM IR output."""
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(llvm_ir)
    
    def _generate_native_output(
        self, llvm_ir: str, out_path: str, src_file: Path, prog: Any, profile: str,
        sanitize: str | None, triple: str | None, freestanding: bool,
        kind: str, links: list[str] | None
    ):
        """Generate native binary with enhanced optimizations."""
        # Get dependency information
        dep_libs, dep_link_args = _dependency_native_link_data(src_file)
        ffi_libs: set[str] = set(dep_libs)
        ffi_libs.update({lib for lib in (links or []) if lib})
        
        _build_native_llvm(
            llvm_ir,
            out_path,
            src_file,
            prog,
            profile=profile,
            sanitize=sanitize,
            triple=triple,
            freestanding=freestanding,
            kind=kind,
            link_libs=sorted(ffi_libs),
            link_args=dep_link_args,
        )
    
    def _build_fingerprint_enhanced(
        self, src_file: Path, target: str, kind: str, emit_ir: str | None,
        strict: bool, freestanding: bool, profile: str, overflow_mode: str,
        sanitize: str | None, triple: str | None, links: list[str] | None
    ) -> str:
        """Build enhanced fingerprint for caching."""
        # Include enhanced optimizer in fingerprint
        from astra.optimizer_enhanced import __file__ as enhanced_opt_file
        from astra.llvm_codegen_enhanced import __file__ as enhanced_codegen_file
        
        parts: list[str] = [f"astra_version={ASTRA_VERSION}"]
        parts.append(f"enhanced_optimizer={_hash_file(Path(enhanced_opt_file))}")
        parts.append(f"enhanced_codegen={_hash_file(Path(enhanced_codegen_file))}")
        
        # Add original fingerprint components
        dep_libs, dep_link_args = _dependency_native_link_data(src_file)
        inputs = [
            {"path": p.as_posix(), "sha256": _sha256_file(p)}
            for p in _collect_input_files(src_file)
        ]
        payload = {
            "src": src_file.resolve().as_posix(),
            "target": target,
            "kind": kind,
            "emit_ir": bool(emit_ir),
            "strict": bool(strict),
            "freestanding": bool(freestanding),
            "profile": profile,
            "overflow_mode": overflow_mode,
            "sanitize": sanitize or "",
            "triple": triple or "",
            "links": sorted(set(links or [])),
            "dep_libs": sorted(dep_libs),
            "dep_link_args": list(dep_link_args),
            "inputs": inputs,
            "enhanced_build": True,
        }
        parts.append(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return _hash("\n".join(parts))
    
    def _get_cache_key(self, src_file: Path, target: str, kind: str, strict: bool,
                      freestanding: bool, emit_ir: str | None, profile: str,
                      overflow_mode: str, sanitize: str | None, triple: str | None,
                      links: list[str] | None) -> str:
        """Get cache key for build."""
        return (
            f"{src_file.resolve().as_posix()}::{target}::{kind}::{int(bool(strict))}::"
            f"{int(bool(freestanding))}::{int(bool(emit_ir))}::{profile}::{overflow_mode}::"
            f"{sanitize or ''}::{triple or ''}::{','.join(sorted(set(links or [])))}::enhanced"
        )


def _hash_file(path: Path) -> str:
    """Hash a single file."""
    return _sha256_file(path)


def _sha256_file(path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _hash(content: str) -> str:
    """Hash string content."""
    return hashlib.sha256(content.encode()).hexdigest()


# Enhanced build function that replaces the original
def build_enhanced(
    src_path: str,
    out_path: str,
    target: str = 'py',
    kind: str = "exe",
    emit_ir: str | None = None,
    strict: bool = False,
    freestanding: bool = False,
    profile: str = "debug",
    overflow: str = "debug",
    sanitize: str | None = None,
    triple: str | None = None,
    links: list[str] | None = None,
) -> str:
    """Enhanced build function with comprehensive optimizations."""
    pipeline = EnhancedBuildPipeline(profile=profile, overflow_mode=overflow)
    return pipeline.build(
        src_path, out_path, target, kind, emit_ir, strict, freestanding,
        profile, overflow, sanitize, triple, links
    )


# Performance benchmarking
def benchmark_build(src_path: str, iterations: int = 5) -> dict:
    """Benchmark build performance."""
    import time
    
    times = []
    for i in range(iterations):
        start = time.time()
        try:
            build_enhanced(src_path, f"benchmark_output_{i}.py", target="py", profile="release")
            times.append(time.time() - start)
        except Exception as e:
            print(f"Benchmark iteration {i} failed: {e}")
    
    if times:
        return {
            "average_time": sum(times) / len(times),
            "min_time": min(times),
            "max_time": max(times),
            "iterations": len(times)
        }
    return {"error": "All iterations failed"}


def compare_optimization_levels(src_path: str) -> dict:
    """Compare debug vs release build performance."""
    import time
    
    results = {}
    
    for profile in ["debug", "release"]:
        start = time.time()
        try:
            build_enhanced(src_path, f"compare_{profile}.py", target="py", profile=profile)
            build_time = time.time() - start
            
            # Run the generated code if it's Python
            try:
                run_start = time.time()
                subprocess.run([sys.executable, f"compare_{profile}.py"], 
                             capture_output=True, text=True, timeout=10)
                run_time = time.time() - run_start
                results[profile] = {"build_time": build_time, "run_time": run_time}
            except Exception as e:
                results[profile] = {"build_time": build_time, "run_error": str(e)}
        except Exception as e:
            results[profile] = {"error": str(e)}
    
    return results
