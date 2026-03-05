"""Build orchestration for parsing, analysis, optimization, and backend emission."""

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
except Exception:  # pragma: no cover - fallback for older runtimes
    import tomli as tomllib

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
    RangeExpr,
    ReturnStmt,
    SizeOfTypeExpr,
    SizeOfValueExpr,
    StructDecl,
    StructLit,
    TryExpr,
    TypeAliasDecl,
    TypeAnnotated,
    Unary,
    UnsafeStmt,
    WhileStmt,
    WildcardPattern,
)
from astra.comptime import run_comptime
from astra.codegen import to_python
from astra.for_lowering import lower_for_loops
from astra.llvm_codegen import to_llvm_ir
from astra.module_resolver import (
    ModuleResolutionError,
    find_project_root,
    package_cache_root,
    resolve_import_path,
    runtime_source_path,
    stdlib_root_path,
)
from astra.optimizer import optimize_program
from astra.parser import parse
from astra.semantic import analyze

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


def _collect_imported_externs(src_file: Path) -> list[ExternFnDecl]:
    visited: set[Path] = set()
    out: list[ExternFnDecl] = []
    stack: list[Path] = []
    try:
        root_prog = parse(src_file.read_text(), filename=str(src_file))
        for item in root_prog.items:
            if not isinstance(item, ImportDecl):
                continue
            try:
                dep = resolve_import_path(item, str(src_file))
            except ModuleResolutionError:
                continue
            stack.append(dep.resolve())
    except Exception:
        return out
    while stack:
        cur = stack.pop()
        if cur in visited:
            continue
        visited.add(cur)
        try:
            text = cur.read_text()
            prog = parse(text, filename=str(cur))
        except Exception:
            continue
        for item in prog.items:
            if isinstance(item, ImportDecl):
                try:
                    dep = resolve_import_path(item, str(cur))
                except ModuleResolutionError:
                    continue
                if dep.exists() and dep not in visited:
                    stack.append(dep)
                continue
            if isinstance(item, ExternFnDecl):
                out.append(item)
    return out


def _collect_imported_items(src_file: Path) -> list[tuple[Any, Path]]:
    visited: set[Path] = set()
    out: list[tuple[Any, Path]] = []
    stack: list[Path] = []
    try:
        root_prog = parse(src_file.read_text(), filename=str(src_file))
    except Exception:
        return out
    for item in root_prog.items:
        if not isinstance(item, ImportDecl):
            continue
        try:
            dep = resolve_import_path(item, str(src_file))
        except ModuleResolutionError:
            continue
        stack.append(dep.resolve())

    while stack:
        cur = stack.pop()
        if cur in visited:
            continue
        visited.add(cur)
        try:
            text = cur.read_text()
            prog = parse(text, filename=str(cur))
        except Exception:
            continue
        for item in prog.items:
            if isinstance(item, ImportDecl):
                try:
                    dep = resolve_import_path(item, str(cur))
                except ModuleResolutionError:
                    continue
                if dep.exists() and dep.resolve() not in visited:
                    stack.append(dep.resolve())
                continue
            out.append((item, cur))
    return out


def _build_fingerprint(
    src_file: Path,
    target: str,
    kind: str,
    emit_ir: str | None,
    strict: bool,
    freestanding: bool,
    profile: str,
    overflow_mode: str,
    sanitize: str | None,
    triple: str | None,
    links: list[str] | None,
) -> str:
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


def _load_project_manifest(src_file: Path) -> dict:
    root = find_project_root(str(src_file))
    if root is None:
        return {}
    manifest = root / "Astra.toml"
    if not manifest.exists():
        return {}
    try:
        data = tomllib.loads(manifest.read_text())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_project_dependencies(src_file: Path) -> dict[str, str]:
    data = _load_project_manifest(src_file)
    deps = data.get("dependencies")
    if isinstance(deps, dict):
        return {str(k): str(v) for k, v in deps.items() if isinstance(k, str) and isinstance(v, str)}
    deps_legacy = data.get("deps")
    if isinstance(deps_legacy, dict):
        return {str(k): str(v) for k, v in deps_legacy.items() if isinstance(k, str) and isinstance(v, str)}
    return {}


def _platform_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("win"):
        return "windows"
    return sys.platform


def _append_unique(dst: list[str], value: str) -> None:
    if value and value not in dst:
        dst.append(value)


def _extract_link_list(raw: object, platform: str) -> list[str]:
    if isinstance(raw, list):
        return [x.strip() for x in raw if isinstance(x, str) and x.strip()]
    if isinstance(raw, dict):
        value = raw.get(platform)
        if isinstance(value, list):
            return [x.strip() for x in value if isinstance(x, str) and x.strip()]
    return []


def _extract_pkg_config_name(raw: object, platform: str) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if isinstance(raw, dict):
        value = raw.get(platform)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _pkg_config_link_args(name: str) -> list[str]:
    pkg_config = shutil.which("pkg-config")
    if pkg_config is None:
        return []
    cp = subprocess.run([pkg_config, "--libs", name], capture_output=True, text=True)
    if cp.returncode != 0:
        return []
    return [arg for arg in shlex.split(cp.stdout.strip()) if arg]


def _dependency_native_link_data(src_file: Path) -> tuple[set[str], list[str]]:
    libs: set[str] = set()
    link_args: list[str] = []
    deps = _load_project_dependencies(src_file)
    project_manifest = _load_project_manifest(src_file)
    pkg_overrides = project_manifest.get("package")
    if not isinstance(pkg_overrides, dict):
        pkg_overrides = {}
    platform = _platform_key()
    cache_root = package_cache_root()
    for name, ver in deps.items():
        manifest = cache_root / name / ver / "Astra.toml"
        data: dict = {}
        if manifest.exists():
            try:
                loaded = tomllib.loads(manifest.read_text())
            except Exception:
                loaded = {}
            if isinstance(loaded, dict):
                data = loaded
        native = data.get("native")
        if isinstance(native, dict):
            for lib in _extract_link_list(native.get("libs"), platform):
                libs.add(lib)
            for lib in _extract_link_list(native.get("link"), platform):
                libs.add(lib)
            pkg_cfg = _extract_pkg_config_name(native.get("pkg_config"), platform)
            if pkg_cfg:
                for arg in _pkg_config_link_args(pkg_cfg):
                    _append_unique(link_args, arg)

        dep_cfg = pkg_overrides.get(name)
        if not isinstance(dep_cfg, dict):
            continue
        for lib in _extract_link_list(dep_cfg.get("link"), platform):
            libs.add(lib)
        pkg_cfg = _extract_pkg_config_name(dep_cfg.get("pkg_config"), platform)
        if pkg_cfg:
            for arg in _pkg_config_link_args(pkg_cfg):
                _append_unique(link_args, arg)

    return libs, link_args


_STRICT_TOP_LEVEL = {FnDecl, StructDecl, EnumDecl, TypeAliasDecl, ImportDecl, ExternFnDecl, LetStmt}
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
    TryExpr,
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
    RangeExpr,
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
    if isinstance(e, TryExpr):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, TypeAnnotated):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, CastExpr):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, RangeExpr):
        _strict_walk_expr(e.start, errs)
        _strict_walk_expr(e.end, errs)
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
        _strict_walk_expr(st.iterable, errs)
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


def _build_native_llvm(
    ir_text: str,
    out_path: str,
    src_file: Path,
    *,
    profile: str,
    sanitize: str | None,
    triple: str | None,
    freestanding: bool,
    kind: str,
    link_libs: list[str] | None = None,
    link_args: list[str] | None = None,
):
    clang = shutil.which("clang")
    if clang is None:
        raise RuntimeError(f"CODEGEN {src_file}:1:1: native target requires `clang` in PATH")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    opt_flag = "-O3" if profile == "release" else "-O0"
    sanitize_flag = f"-fsanitize={sanitize}" if sanitize else None
    with tempfile.TemporaryDirectory(prefix="astra-native-") as td:
        ll_path = Path(td) / "module.ll"
        ll_path.write_text(ir_text)
        if kind == "lib":
            cmd = [clang, opt_flag, "-shared", "-fPIC", str(ll_path), "-o", str(out)]
            if not freestanding:
                runtime_c = runtime_source_path()
                if runtime_c is None:
                    raise RuntimeError(
                        f"CODEGEN {src_file}:1:1: missing runtime source; set ASTRA_RUNTIME_C_PATH or install bundled runtime"
                    )
                cmd.insert(-2, str(runtime_c))
                cmd.insert(-2, "-lm")
        elif freestanding:
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
            runtime_c = runtime_source_path()
            if runtime_c is None:
                raise RuntimeError(
                    f"CODEGEN {src_file}:1:1: missing runtime source; set ASTRA_RUNTIME_C_PATH or install bundled runtime"
                )
            cmd = [clang, opt_flag, str(ll_path), str(runtime_c), "-lm", "-o", str(out)]
        if link_libs:
            for lib in sorted(set(link_libs)):
                if lib:
                    cmd.append(f"-l{lib}")
        if sanitize_flag is not None:
            cmd.append(sanitize_flag)
        if link_args:
            cmd.extend([arg for arg in link_args if arg])
        if triple:
            cmd.insert(1, f"--target={triple}")
        cp = subprocess.run(cmd, capture_output=True, text=True)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout or "").strip()
            raise RuntimeError(f"CODEGEN {src_file}:1:1: clang link failed{': ' + detail if detail else ''}")
    if kind == "exe":
        out.chmod(out.stat().st_mode | 0o111)


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

def build(
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
):
    """Compile an Astra source file into Python, LLVM IR, or native output.
    
    Parameters:
        src_path: Filesystem path input used by this routine.
        out_path: Filesystem path input used by this routine.
        target: Input value used by this routine.
        kind: Input value used by this routine.
        emit_ir: Input value used by this routine.
        strict: Input value used by this routine.
        freestanding: Whether hosted-runtime features are disallowed.
        profile: Build profile selector, typically `debug` or `release`.
        overflow: Integer overflow behavior mode requested by the caller.
        sanitize: Optional native sanitizer (`address`, `undefined`, `thread`).
        triple: Input value used by this routine.
    
    Returns:
        Value produced by the routine, if any.
    """
    src_file = Path(src_path)
    if kind not in {"exe", "lib"}:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported build kind {kind}")
    if profile not in {"debug", "release"}:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported profile {profile}")
    if sanitize not in {None, "address", "undefined", "thread"}:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported sanitizer {sanitize}")
    if sanitize is not None and target != "native":
        raise RuntimeError(f"BUILD {src_file}:1:1: sanitizer requires --target native")
    if sanitize is not None and freestanding:
        raise RuntimeError(f"BUILD {src_file}:1:1: sanitizer is unsupported with --freestanding")
    overflow_mode = _resolve_overflow_mode(profile, overflow, check=False)
    digest = _build_fingerprint(
        src_file,
        target,
        kind,
        emit_ir,
        strict,
        freestanding,
        profile,
        overflow_mode,
        sanitize,
        triple,
        links,
    )
    cache_key = (
        f"{src_file.resolve().as_posix()}::{target}::{kind}::{int(bool(strict))}::{int(bool(freestanding))}::"
        f"{int(bool(emit_ir))}::{profile}::{overflow_mode}::{sanitize or ''}::{triple or ''}::{','.join(sorted(set(links or [])))}"
    )
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if cache.get(cache_key) == digest and Path(out_path).exists():
        return 'cached'
    src = src_file.read_text()
    prog = parse(src, filename=str(src_file))
    imported_items = _collect_imported_items(src_file)
    if imported_items:
        fn_keys = {
            (
                item.name,
                tuple(item.params),
                item.ret,
                bool(getattr(item, "is_variadic", False)),
                bool(getattr(item, "unsafe", False)),
                isinstance(item, ExternFnDecl),
                bool(getattr(item, "is_impl", False)),
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
                    bool(getattr(item, "is_impl", False)),
                )
                if key in fn_keys:
                    continue
                fn_keys.add(key)
                prog.items.append(item)
                continue
            if isinstance(item, (StructDecl, EnumDecl, TypeAliasDecl)):
                if item.name in named_types:
                    continue
                named_types.add(item.name)
                prog.items.append(item)
                continue
            if isinstance(item, LetStmt):
                # Imported top-level constants are carried when uniquely named.
                if any(isinstance(existing, LetStmt) and existing.name == item.name for existing in prog.items):
                    continue
                prog.items.append(item)
    required_entrypoint = None if kind == "lib" else ("_start" if freestanding else "main")
    run_comptime(prog, filename=str(src_file), overflow_mode=overflow_mode)
    analyze(
        prog,
        filename=str(src_file),
        freestanding=freestanding,
        require_entrypoint=required_entrypoint,
    )
    dep_libs, dep_link_args = _dependency_native_link_data(src_file)
    ffi_libs: set[str] = set(getattr(prog, "ffi_libs", set()))
    ffi_libs.update(dep_libs)
    ffi_libs.update({lib for lib in (links or []) if lib})
    lower_for_loops(prog)
    optimize_program(prog)
    if strict:
        _strict_validate_program(prog, src_file)
    llvm_ir: str | None = None
    if target in {"llvm", "native"} or emit_ir:
        llvm_ir = to_llvm_ir(
            prog,
            freestanding=freestanding,
            overflow_mode=overflow_mode,
            triple=triple,
            profile=profile,
            filename=str(src_file),
        )
    if freestanding and llvm_ir is not None:
        _require_runtime_free_freestanding(llvm_ir, src_file)
    if emit_ir:
        assert llvm_ir is not None
        p = Path(emit_ir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(llvm_ir)
    if target == "py":
        out = to_python(prog, freestanding=freestanding, overflow_mode=overflow_mode, emit_entrypoint=(kind == "exe"))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(out)
    elif target == "llvm":
        assert llvm_ir is not None
        out = llvm_ir
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(out)
    elif target == "native":
        assert llvm_ir is not None
        _build_native_llvm(
            llvm_ir,
            out_path,
            src_file,
            profile=profile,
            sanitize=sanitize,
            triple=triple,
            freestanding=freestanding,
            kind=kind,
            link_libs=sorted(ffi_libs),
            link_args=dep_link_args,
        )
    else:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported target {target}")
    cache[cache_key] = digest
    CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=2))
    return 'built'
