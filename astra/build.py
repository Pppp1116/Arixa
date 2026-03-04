import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from astra import __version__ as ASTRA_VERSION
from astra.ast import (
    ArrayLit,
    AlignOfTypeExpr,
    AlignOfValueExpr,
    AssignStmt,
    AwaitExpr,
    BitSizeOfTypeExpr,
    Binary,
    BoolLit,
    BreakStmt,
    Call,
    CastExpr,
    ComptimeStmt,
    ContinueStmt,
    DeferStmt,
    DropStmt,
    EnumDecl,
    ExprStmt,
    ExternFnDecl,
    FieldExpr,
    FnDecl,
    ForStmt,
    IfStmt,
    ImportDecl,
    IndexExpr,
    LetStmt,
    Literal,
    MatchStmt,
    MaxValTypeExpr,
    MinValTypeExpr,
    Name,
    NilLit,
    Program,
    ReturnStmt,
    SizeOfTypeExpr,
    SizeOfValueExpr,
    StructDecl,
    StructLit,
    TypeAliasDecl,
    TypeAnnotated,
    Unary,
    UnsafeStmt,
    WhileStmt,
    WildcardPattern,
)
from astra.comptime import run_comptime
from astra.codegen import to_python
from astra.llvm_codegen import to_llvm_ir
from astra.module_resolver import (
    ModuleResolutionError,
    resolve_import_path,
    runtime_source_path,
    stdlib_root_path,
)
from astra.optimizer import optimize_program
from astra.reachability import prune_unreachable_items
from astra.parser import parse
from astra.semantic import analyze
from astra.profiler import profiler
from astra.parallel import parse_files_parallel, is_parallel_enabled
from astra.symbols import build_global_symbol_table, validate_symbol_consistency
from astra.parallel_semantic import analyze_program_parallel
from astra.parallel_ir import optimize_program_parallel

CACHE = Path('.astra-cache.json')
_REPO_ROOT = Path(__file__).resolve().parent.parent
_TOOLCHAIN_STAMP: str | None = None

def _hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _iter_tree_files(root: Path, suffixes: set[str] | None = None) -> list[Path]:
    if not root.exists():
        return []
    out: list[Path] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        if suffixes is not None and p.suffix not in suffixes:
            continue
        out.append(p)
    return out


def _toolchain_stamp() -> str:
    global _TOOLCHAIN_STAMP
    if _TOOLCHAIN_STAMP is not None:
        return _TOOLCHAIN_STAMP
    parts: list[str] = [f"astra_version={ASTRA_VERSION}"]
    for p in _iter_tree_files(_REPO_ROOT / "astra", {".py"}):
        rel = p.relative_to(_REPO_ROOT).as_posix()
        parts.append(f"{rel}:{_sha256_file(p)}")
    runtime_c = runtime_source_path()
    if runtime_c is not None:
        parts.append(f"{runtime_c.as_posix()}:{_sha256_file(runtime_c)}")
    std_root = stdlib_root_path()
    if std_root is not None:
        for p in _iter_tree_files(std_root, {".astra"}):
            rel = p.relative_to(std_root).as_posix()
            parts.append(f"stdlib:{rel}:{_sha256_file(p)}")
    _TOOLCHAIN_STAMP = _hash("\n".join(parts))
    return _TOOLCHAIN_STAMP


def _collect_input_files(src_file: Path) -> list[Path]:
    """Collect all input files (sequential for now)"""
    visited: set[Path] = set()
    stack: list[Path] = [src_file.resolve()]
    while stack:
        cur = stack.pop()
        if cur in visited:
            continue
        visited.add(cur)
        try:
            text = cur.read_text()
        except OSError:
            continue
        try:
            prog = parse(text, filename=str(cur))
        except Exception:
            # Fallback: keep current file in fingerprint even if it does not parse yet.
            continue
        for item in prog.items:
            if not isinstance(item, ImportDecl):
                continue
            try:
                dep = resolve_import_path(item, str(cur))
            except ModuleResolutionError:
                continue
            if dep.exists() and dep not in visited:
                stack.append(dep)
    return sorted(visited)


def _build_fingerprint(
    src_file: Path,
    target: str,
    emit_ir: str | None,
    strict: bool,
    freestanding: bool,
    profile: str,
    overflow_mode: str,
    triple: str | None,
    opt_size: bool,
) -> str:
    inputs = [
        {"path": p.as_posix(), "sha256": _sha256_file(p)}
        for p in _collect_input_files(src_file)
    ]
    payload = {
        "src": src_file.resolve().as_posix(),
        "target": target,
        "emit_ir": bool(emit_ir),
        "strict": bool(strict),
        "freestanding": bool(freestanding),
        "profile": profile,
        "overflow_mode": overflow_mode,
        "triple": triple or "",
        "opt_size": bool(opt_size),
        "inputs": inputs,
        "toolchain": _toolchain_stamp(),
    }
    return _hash(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _resolve_overflow_mode(profile: str, overflow: str, *, check: bool = False) -> str:
    if overflow not in {"trap", "wrap", "debug"}:
        raise RuntimeError(f"BUILD <input>:1:1: unsupported overflow mode {overflow}")
    if overflow == "trap":
        return "trap"
    if overflow == "wrap":
        return "wrap"
    if check:
        return "trap"
    return "trap" if profile == "debug" else "wrap"


_STRICT_TOP_LEVEL = {FnDecl, StructDecl, EnumDecl, TypeAliasDecl, ImportDecl, ExternFnDecl}
_STRICT_STMTS = {LetStmt, AssignStmt, ReturnStmt, ExprStmt, DropStmt, IfStmt, MatchStmt, WhileStmt, ForStmt, BreakStmt, ContinueStmt, ComptimeStmt, DeferStmt, UnsafeStmt}
_STRICT_EXPRS = {
    Literal,
    BoolLit,
    NilLit,
    Name,
    Unary,
    Binary,
    Call,
    IndexExpr,
    FieldExpr,
    ArrayLit,
    StructLit,
    AwaitExpr,
    TypeAnnotated,
    CastExpr,
    SizeOfTypeExpr,
    AlignOfTypeExpr,
    BitSizeOfTypeExpr,
    MaxValTypeExpr,
    MinValTypeExpr,
    SizeOfValueExpr,
    AlignOfValueExpr,
    WildcardPattern,
}
_STRICT_UNARY_OPS = {"-", "!", "~", "&", "&mut", "*"}
_STRICT_BINARY_OPS = {
    "+",
    "-",
    "*",
    "/",
    "%",
    "&",
    "|",
    "^",
    "<<",
    ">>",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
    "&&",
    "||",
    "??",
}
_STRICT_ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}


def _strict_walk_expr(e: object, errs: list[str]) -> None:
    if type(e) not in _STRICT_EXPRS:
        errs.append(f"unsupported expression node {type(e).__name__}")
        return
    if isinstance(e, Unary):
        if e.op not in _STRICT_UNARY_OPS:
            errs.append(f"unsupported unary op {e.op}")
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, Binary):
        if e.op not in _STRICT_BINARY_OPS:
            errs.append(f"unsupported binary op {e.op}")
        _strict_walk_expr(e.left, errs)
        _strict_walk_expr(e.right, errs)
        return
    if isinstance(e, Call):
        _strict_walk_expr(e.fn, errs)
        for arg in e.args:
            _strict_walk_expr(arg, errs)
        return
    if isinstance(e, IndexExpr):
        _strict_walk_expr(e.obj, errs)
        _strict_walk_expr(e.index, errs)
        return
    if isinstance(e, FieldExpr):
        _strict_walk_expr(e.obj, errs)
        return
    if isinstance(e, ArrayLit):
        for elem in e.elements:
            _strict_walk_expr(elem, errs)
        return
    if isinstance(e, StructLit):
        for _, field_expr in e.fields:
            _strict_walk_expr(field_expr, errs)
        return
    if isinstance(e, AwaitExpr):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, TypeAnnotated):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, CastExpr):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, (SizeOfTypeExpr, AlignOfTypeExpr, BitSizeOfTypeExpr, MaxValTypeExpr, MinValTypeExpr)):
        return
    if isinstance(e, (SizeOfValueExpr, AlignOfValueExpr)):
        _strict_walk_expr(e.expr, errs)
        return


def _strict_walk_stmt(st: object, errs: list[str]) -> None:
    if type(st) not in _STRICT_STMTS:
        errs.append(f"unsupported statement node {type(st).__name__}")
        return
    if isinstance(st, LetStmt):
        _strict_walk_expr(st.expr, errs)
        return
    if isinstance(st, AssignStmt):
        if st.op not in _STRICT_ASSIGN_OPS:
            errs.append(f"unsupported assignment op {st.op}")
        _strict_walk_expr(st.target, errs)
        _strict_walk_expr(st.expr, errs)
        return
    if isinstance(st, ReturnStmt):
        if st.expr is not None:
            _strict_walk_expr(st.expr, errs)
        return
    if isinstance(st, ExprStmt):
        _strict_walk_expr(st.expr, errs)
        return
    if isinstance(st, DropStmt):
        _strict_walk_expr(st.expr, errs)
        return
    if isinstance(st, IfStmt):
        _strict_walk_expr(st.cond, errs)
        for x in st.then_body:
            _strict_walk_stmt(x, errs)
        for x in st.else_body:
            _strict_walk_stmt(x, errs)
        return
    if isinstance(st, MatchStmt):
        _strict_walk_expr(st.expr, errs)
        for pat, body in st.arms:
            _strict_walk_expr(pat, errs)
            for x in body:
                _strict_walk_stmt(x, errs)
        return
    if isinstance(st, WhileStmt):
        _strict_walk_expr(st.cond, errs)
        for x in st.body:
            _strict_walk_stmt(x, errs)
        return
    if isinstance(st, ForStmt):
        if st.init is not None:
            if isinstance(st.init, LetStmt):
                _strict_walk_stmt(st.init, errs)
            else:
                _strict_walk_expr(st.init, errs)
        if st.cond is not None:
            _strict_walk_expr(st.cond, errs)
        if st.step is not None:
            if isinstance(st.step, AssignStmt):
                _strict_walk_stmt(st.step, errs)
            else:
                _strict_walk_expr(st.step, errs)
        for x in st.body:
            _strict_walk_stmt(x, errs)
        return
    if isinstance(st, ComptimeStmt):
        for x in st.body:
            _strict_walk_stmt(x, errs)
        return
    if isinstance(st, DeferStmt):
        _strict_walk_expr(st.expr, errs)
        return
    if isinstance(st, UnsafeStmt):
        for x in st.body:
            _strict_walk_stmt(x, errs)
        return


def _strict_validate_program(prog: Program, src_file: Path) -> None:
    errs: list[str] = []
    for item in prog.items:
        if type(item) not in _STRICT_TOP_LEVEL:
            errs.append(f"unsupported top-level node {type(item).__name__}")
            continue
        if isinstance(item, FnDecl):
            for st in item.body:
                _strict_walk_stmt(st, errs)
    if errs:
        details = "; ".join(sorted(set(errs)))
        raise RuntimeError(f"CODEGEN {src_file}:1:1: strict mode rejected backend lowering: {details}")


def _build_native_llvm(ir_text: str, out_path: str, src_file: Path, *, profile: str, triple: str | None, freestanding: bool, opt_size: bool = False):
    clang = shutil.which("clang")
    if clang is None:
        raise RuntimeError(f"CODEGEN {src_file}:1:1: native target requires `clang` in PATH")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    opt_flag = "-Oz" if opt_size else ("-O3" if profile == "release" else "-O0")
    print(f"Using clang with optimization: {opt_flag}")
    
    with tempfile.TemporaryDirectory(prefix="astra-native-") as td:
        ll_path = Path(td) / "module.ll"
        ll_path.write_text(ir_text)
        
        if freestanding:
            print("Building freestanding executable...")
            cmd = [
                clang,
                opt_flag,
                str(ll_path),
                "-nostdlib",
                "-nostartfiles",
                "-Wl,-e,_start",
                "-o",
                str(out),
            ]
        else:
            print("Building hosted executable with runtime...")
            runtime_c = runtime_source_path()
            if runtime_c is None:
                raise RuntimeError(
                    f"CODEGEN {src_file}:1:1: missing runtime source; set ASTRA_RUNTIME_C_PATH or install bundled runtime"
                )
            cmd = [clang, opt_flag, str(ll_path), str(runtime_c), "-lm", "-o", str(out)]

        if opt_size:
            cmd[1:1] = ["-flto", "-s"]
        
        if triple:
            cmd.insert(1, f"--target={triple}")
            print(f"Using target triple: {triple}")
        
        print(f"Running clang: {' '.join(cmd)}")
        cp = subprocess.run(cmd, capture_output=True, text=True)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout or "").strip()
            raise RuntimeError(f"CODEGEN {src_file}:1:1: clang link failed{': ' + detail if detail else ''}")
        
        print(f"Clang compilation successful")
    out.chmod(out.stat().st_mode | 0o111)
    print(f"Made executable: {out}")


def _require_runtime_free_freestanding(ir_text: str, src_file: Path) -> None:
    syms = sorted(
        {
            s
            for s in re.findall(r"@((?:astra|__astra)_[A-Za-z0-9_]+)", ir_text)
            if not s.startswith("__astra_fs_")
        }
    )
    if syms:
        raise RuntimeError(
            f"CODEGEN {src_file}:1:1: freestanding build cannot depend on runtime symbols: {', '.join(syms)}"
        )
    externs = sorted(
        {
            name
            for name in re.findall(r"(?m)^\s*declare\s+[^@]*@([A-Za-z_.$][A-Za-z0-9_.$]*)\(", ir_text)
            if not name.startswith("llvm.")
        }
    )
    if externs:
        raise RuntimeError(
            f"CODEGEN {src_file}:1:1: freestanding build cannot depend on external host symbols: {', '.join(externs)}"
        )

def _parse_files_parallel(file_paths: list[Path]) -> dict[Path, Any]:
    """Parse multiple files in parallel and return ASTs"""
    if not file_paths:
        return {}
    
    print(f"Parsing {len(file_paths)} files in parallel...")
    with profiler.section("parallel_parse"):
        parse_results = parse_files_parallel(file_paths)
    
    # Check for parsing errors
    errors = []
    asts = {}
    for file_path, result in parse_results.items():
        if isinstance(result, Exception):
            errors.append(f"PARSE {file_path}:1:1: {result}")
        else:
            asts[file_path] = result
    
    if errors:
        raise RuntimeError("\n".join(errors))
    
    return asts


def _merge_programs(asts: dict[Path, Any]) -> Any:
    """Merge multiple AST programs into a single program."""
    from astra.ast import Program

    all_items = []
    for file_path in sorted(asts.keys()):
        ast = asts[file_path]
        if hasattr(ast, "items"):
            items = list(ast.items)
        elif isinstance(ast, list):
            items = list(ast)
        else:
            items = [ast]
        for item in items:
            setattr(item, "_source_file", str(file_path))
            all_items.append(item)

    return Program(items=all_items)


def build(
    src_path: str,
    out_path: str,
    target: str = 'py',
    emit_ir: str | None = None,
    strict: bool = False,
    freestanding: bool = False,
    profile: str = "debug",
    overflow: str = "debug",
    triple: str | None = None,
    *,
    profile_compile: bool = False,
    threads: int | None = None,
    opt_size: bool = False,
):
    src_file = Path(src_path)
    print(f"Building {src_file} -> {out_path} (target: {target})")
    
    # Configure profiler and threads environment
    profiler.enable(profile_compile)
    if threads is not None and threads > 0:
        os.environ["ASTRA_THREADS"] = str(threads)
    else:
        os.environ.pop("ASTRA_THREADS", None)
    
    if profile not in {"debug", "release"}:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported profile {profile}")
    overflow_mode = _resolve_overflow_mode(profile, overflow, check=False)
    digest = _build_fingerprint(src_file, target, emit_ir, strict, freestanding, profile, overflow_mode, triple, opt_size)
    cache_key = (
        f"{src_file.resolve().as_posix()}::{target}::{int(bool(strict))}::{int(bool(freestanding))}::"
        f"{int(bool(emit_ir))}::{profile}::{overflow_mode}::{triple or ''}::{int(bool(opt_size))}"
    )
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if cache.get(cache_key) == digest and Path(out_path).exists():
        print(f"Using cached build for {src_file}")
        return 'cached'
    
    print(f"Parsing {src_file}...")
    
    # Collect all input files
    input_files = _collect_input_files(src_file)
    print(f"Found {len(input_files)} input files")
    
    # Parse files (parallel if enabled and multiple files)
    if len(input_files) > 1 and is_parallel_enabled():
        asts = _parse_files_parallel(input_files)
        prog = _merge_programs(asts)
        
        # Build global symbol table for parallel semantic analysis
        symbol_table = build_global_symbol_table(asts)
        
        # Validate symbol table consistency
        symbol_errors = validate_symbol_consistency(symbol_table)
        if symbol_errors:
            raise RuntimeError("\n".join(f"SYMBOL {err}" for err in symbol_errors))
    else:
        # Sequential parsing for single file or when parallel disabled
        src = src_file.read_text()
        with profiler.section("lex/parse+ast"):
            prog = parse(src, filename=str(src_file))
        
        # Create symbol table for single file
        symbol_table = build_global_symbol_table({src_file: prog})
    
    if freestanding and target == "native":
        has_start = any(isinstance(item, FnDecl) and item.name == "_start" for item in prog.items)
        if not has_start:
            raise RuntimeError(f"BUILD {src_file}:1:1: freestanding native target requires fn _start()")
    
    print("Running comptime evaluation...")
    with profiler.section("comptime"):
        run_comptime(prog, filename=str(src_file), overflow_mode=overflow_mode)
    
    print("Running semantic analysis...")
    with profiler.section("semantic"):
        if len(input_files) > 1 and is_parallel_enabled():
            # Parallel semantic analysis using frozen symbol table
            analyze_program_parallel(prog, symbol_table, str(src_file), freestanding)
        else:
            # Sequential semantic analysis
            analyze(prog, filename=str(src_file), freestanding=freestanding)
    
    print("Running reachability + dead-code elimination...")
    with profiler.section("reachability"):
        entry = "_start" if (freestanding and target == "native") else "main"
        prune_unreachable_items(prog, entry=entry)

    print("Running optimization...")
    with profiler.section("ir_opts"):
        if len(input_files) > 1 and is_parallel_enabled():
            # Parallel IR optimization
            prog = optimize_program_parallel(prog)
        else:
            # Sequential optimization
            optimize_program(prog)
    
    if strict:
        _strict_validate_program(prog, src_file)
    
    llvm_ir: str | None = None
    if target in {"llvm", "native"} or emit_ir:
        print("Generating LLVM IR...")
        with profiler.section("codegen_ir"):
            llvm_ir = to_llvm_ir(
                prog,
                freestanding=freestanding,
                overflow_mode=overflow_mode,
                triple=triple,
                profile=profile,
            )
    
    if freestanding and llvm_ir is not None:
        _require_runtime_free_freestanding(llvm_ir, src_file)
    
    if emit_ir:
        assert llvm_ir is not None
        p = Path(emit_ir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(llvm_ir)
        print(f"Wrote LLVM IR to {emit_ir}")
    
    if target == "py":
        print("Generating Python code...")
        with profiler.section("codegen_py"):
            out = to_python(prog, freestanding=freestanding, overflow_mode=overflow_mode)
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(out)
        print(f"Wrote Python output to {out_path}")
    elif target == "llvm":
        assert llvm_ir is not None
        out = llvm_ir
        with profiler.section("link_emit"):
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(out)
        print(f"Wrote LLVM IR to {out_path}")
    elif target == "native":
        assert llvm_ir is not None
        print("Compiling to native executable...")
        with profiler.section("link_native"):
            _build_native_llvm(llvm_ir, out_path, src_file, profile=profile, triple=triple, freestanding=freestanding, opt_size=opt_size)
        print(f"Wrote native executable to {out_path}")
    else:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported target {target}")
    
    cache[cache_key] = digest
    CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=2))
    # If profiling, print a summary at the end deterministically
    if profiler.enabled:
        print(profiler.to_text())
    print(f"Build completed successfully: {src_file}")
    return 'built'
