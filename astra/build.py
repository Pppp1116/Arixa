import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from astra import __version__ as ASTRA_VERSION
from astra.ast import (
    ArrayLit,
    AlignOfTypeExpr,
    AlignOfValueExpr,
    AssignStmt,
    AwaitExpr,
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
    Name,
    NilLit,
    Program,
    ReturnStmt,
    SizeOfTypeExpr,
    SizeOfValueExpr,
    StructDecl,
    TypeAliasDecl,
    TypeAnnotated,
    Unary,
    WhileStmt,
)
from astra.comptime import run_comptime
from astra.codegen import to_python, to_x86_64
from astra.ir import lower
from astra.optimizer import optimize, optimize_program
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
    for p in _iter_tree_files(_REPO_ROOT / "runtime"):
        rel = p.relative_to(_REPO_ROOT).as_posix()
        parts.append(f"{rel}:{_sha256_file(p)}")
    for p in _iter_tree_files(_REPO_ROOT / "stdlib", {".astra"}):
        rel = p.relative_to(_REPO_ROOT).as_posix()
        parts.append(f"{rel}:{_sha256_file(p)}")
    _TOOLCHAIN_STAMP = _hash("\n".join(parts))
    return _TOOLCHAIN_STAMP


def _resolve_import_path(path: list[str], from_file: Path) -> Path:
    if path and path[0] == "stdlib":
        return _REPO_ROOT / "stdlib" / f"{path[-1]}.astra"
    return from_file.parent / f"{'/'.join(path)}.astra"


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
            dep = _resolve_import_path(item.path, cur).resolve()
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
_STRICT_STMTS = {LetStmt, AssignStmt, ReturnStmt, ExprStmt, DropStmt, IfStmt, MatchStmt, WhileStmt, ForStmt, BreakStmt, ContinueStmt, ComptimeStmt, DeferStmt}
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
    AwaitExpr,
    TypeAnnotated,
    CastExpr,
    SizeOfTypeExpr,
    AlignOfTypeExpr,
    SizeOfValueExpr,
    AlignOfValueExpr,
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
    if isinstance(e, AwaitExpr):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, TypeAnnotated):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, CastExpr):
        _strict_walk_expr(e.expr, errs)
        return
    if isinstance(e, (SizeOfTypeExpr, AlignOfTypeExpr)):
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


def _build_native_x86_64(asm: str, out_path: str, src_file: Path):
    nasm = shutil.which("nasm")
    cc = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    ld = shutil.which("ld")
    if nasm is None or (cc is None and ld is None):
        raise RuntimeError(f"CODEGEN {src_file}:1:1: native target requires `nasm` and a linker (`cc`/`ld`) in PATH")
    runtime_asm = Path(__file__).resolve().parent.parent / "runtime" / "x86_64_linux_runtime.s"
    if not runtime_asm.exists():
        raise RuntimeError(f"CODEGEN {src_file}:1:1: missing runtime object source at {runtime_asm}")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="astra-native-") as td:
        asm_path = Path(td) / "module.s"
        obj_path = Path(td) / "module.o"
        rt_obj_path = Path(td) / "runtime.o"
        asm_path.write_text(asm)
        cp = subprocess.run([nasm, "-felf64", str(asm_path), "-o", str(obj_path)], capture_output=True, text=True)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout or "").strip()
            raise RuntimeError(f"CODEGEN {src_file}:1:1: nasm failed{': ' + detail if detail else ''}")
        cp = subprocess.run([nasm, "-felf64", str(runtime_asm), "-o", str(rt_obj_path)], capture_output=True, text=True)
        if cp.returncode != 0:
            detail = (cp.stderr or cp.stdout or "").strip()
            raise RuntimeError(f"CODEGEN {src_file}:1:1: runtime assemble failed{': ' + detail if detail else ''}")
        if cc is not None:
            cp = subprocess.run([cc, "-nostdlib", "-no-pie", str(obj_path), str(rt_obj_path), "-lgcc", "-o", str(out)], capture_output=True, text=True)
            if cp.returncode != 0:
                detail = (cp.stderr or cp.stdout or "").strip()
                raise RuntimeError(f"CODEGEN {src_file}:1:1: link failed via cc{': ' + detail if detail else ''}")
        else:
            cp = subprocess.run([ld, str(obj_path), str(rt_obj_path), "-o", str(out)], capture_output=True, text=True)
            if cp.returncode != 0:
                detail = (cp.stderr or cp.stdout or "").strip()
                raise RuntimeError(f"CODEGEN {src_file}:1:1: ld failed{': ' + detail if detail else ''}")
    out.chmod(out.stat().st_mode | 0o111)

def build(
    src_path: str,
    out_path: str,
    target: str = 'py',
    emit_ir: str | None = None,
    strict: bool = False,
    freestanding: bool = False,
    profile: str = "debug",
    overflow: str = "debug",
):
    src_file = Path(src_path)
    if profile not in {"debug", "release"}:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported profile {profile}")
    overflow_mode = _resolve_overflow_mode(profile, overflow, check=False)
    digest = _build_fingerprint(src_file, target, emit_ir, strict, freestanding, profile, overflow_mode)
    cache_key = (
        f"{src_file.resolve().as_posix()}::{target}::{int(bool(strict))}::{int(bool(freestanding))}::"
        f"{int(bool(emit_ir))}::{profile}::{overflow_mode}"
    )
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    if cache.get(cache_key) == digest and Path(out_path).exists():
        return 'cached'
    src = src_file.read_text()
    prog = parse(src, filename=str(src_file))
    run_comptime(prog, filename=str(src_file), overflow_mode=overflow_mode)
    analyze(prog, filename=str(src_file), freestanding=freestanding)
    optimize_program(prog)
    if strict:
        _strict_validate_program(prog, src_file)
    ir = optimize(lower(prog))
    if emit_ir:
        p = Path(emit_ir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps([{"name": f.name, "ops": f.ops} for f in ir.funcs], indent=2))
    if target == "py":
        out = to_python(prog, freestanding=freestanding, overflow_mode=overflow_mode)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(out)
    elif target == "x86_64":
        out = to_x86_64(prog, freestanding=freestanding, overflow_mode=overflow_mode)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(out)
    elif target == "native":
        asm = to_x86_64(prog, freestanding=freestanding, overflow_mode=overflow_mode)
        _build_native_x86_64(asm, out_path, src_file)
    else:
        raise RuntimeError(f"BUILD {src_file}:1:1: unsupported target {target}")
    cache[cache_key] = digest
    CACHE.write_text(json.dumps(dict(sorted(cache.items())), indent=2))
    return 'built'
