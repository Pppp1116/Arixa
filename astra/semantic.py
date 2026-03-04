from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path

from astra.ast import *
from astra.int_types import is_int_type_name, parse_int_type_name
from astra.layout import LayoutError, canonical_type as _layout_canonical_type, layout_of_type
from astra.module_resolver import ModuleResolutionError, resolve_import_path, get_imported_symbols


class SemanticError(Exception):
    pass


def _diag(filename: str, line: int, col: int, msg: str) -> str:
    return f"SEM {filename}:{line}:{col}: {msg}"


FLOAT_TYPES = {"f32", "f64"}
PRIMITIVES = {"Int", "isize", "usize", "Float", "f32", "f64", "String", "str", "Bool", "Any", "Void", "Never", "Bytes"}
COPY_SCALAR_TYPES = {"Float", "f32", "f64", "Bool"}
NONE_LIT_TYPE = "<none>"


def _is_option_type(typ: Any) -> bool:
    t = type_text(typ)
    return t.startswith("Option<") and t.endswith(">")


def _option_inner(typ: Any) -> str:
    t = type_text(typ)
    return t[7:-1]


def _is_vec_type(typ: Any) -> bool:
    t = type_text(typ)
    return t.startswith("Vec<") and t.endswith(">")


def _vec_inner(typ: Any) -> str:
    t = type_text(typ)
    return t[4:-1]


def _is_slice_type(typ: Any) -> bool:
    t = type_text(typ)
    return t.startswith("[") and t.endswith("]")


def _slice_inner(typ: Any) -> str:
    t = type_text(typ)
    return t[1:-1]


def _strip_ref(typ: Any) -> str:
    t = _canonical_type(typ)
    if t.startswith("&mut "):
        return t[5:]
    if t.startswith("&"):
        return t[1:]
    return t


def _is_ref_type(typ: Any) -> bool:
    return _canonical_type(typ).startswith("&")


def _is_mut_ref_type(typ: Any) -> bool:
    return _canonical_type(typ).startswith("&mut ")


def _canonical_type(typ: Any) -> str:
    t = type_text(typ)
    if t == "Bytes":
        return "Vec<u8>"
    if _is_option_type(t):
        return f"Option<{_canonical_type(_option_inner(t))}>"
    if t.startswith("&mut "):
        return f"&mut {_canonical_type(t[5:])}"
    if t.startswith("&"):
        return f"&{_canonical_type(t[1:])}"
    if _is_slice_type(t):
        return f"[{_canonical_type(_slice_inner(t))}]"
    if _is_vec_type(t):
        return f"Vec<{_canonical_type(_vec_inner(t))}>"
    return t


def _int_info(typ: str) -> tuple[int, bool] | None:
    parsed = parse_int_type_name(_canonical_type(typ))
    if parsed is None:
        return None
    bits, signed = parsed
    return bits, signed


def _is_int_type(typ: str) -> bool:
    return _int_info(typ) is not None


def _is_float_type(typ: str) -> bool:
    return _canonical_type(typ) in {"Float", "f32", "f64"}


def _is_text_type(typ: str) -> bool:
    c = _canonical_type(typ)
    return c in {"String", "str", "&str", "&mut str"}


def _is_numeric_scalar_type(typ: str) -> bool:
    return _is_int_type(typ) or _is_float_type(typ)


def _is_unsized_value_type(typ: str) -> bool:
    c = _canonical_type(typ)
    return c == "str" or _is_slice_type(c)


def _is_copy_type(typ: str) -> bool:
    c = _canonical_type(typ)
    if _is_int_type(c):
        return True
    if c in COPY_SCALAR_TYPES:
        return True
    return _is_ref_type(c) and not _is_mut_ref_type(c)


def _validate_decl_type(typ: Any, filename: str, line: int, col: int) -> None:
    c = _canonical_type(typ)
    info = _int_info(c)
    if info is None:
        return
    bits, signed = info
    if signed and bits == 1:
        raise SemanticError(_diag(filename, line, col, "i1 can only represent 0 and -1, did you mean u1?"))


@dataclass
class BuiltinSig:
    args: list[str] | None
    ret: str


@dataclass(frozen=True)
class Span:
    filename: str
    line: int
    col: int

    @classmethod
    def at(cls, filename: str, line: int, col: int) -> "Span":
        return cls(filename=filename, line=line, col=col)


BUILTIN_SIGS: dict[str, BuiltinSig] = {
    "print": BuiltinSig(["Any"], "Void"),
    "len": BuiltinSig(["Any"], "Int"),
    "read_file": BuiltinSig(["String"], "String"),
    "write_file": BuiltinSig(["String", "String"], "Int"),
    "args": BuiltinSig([], "Any"),
    "arg": BuiltinSig(["Int"], "String"),
    "spawn": BuiltinSig(None, "Int"),
    "join": BuiltinSig(["Int"], "Any"),
    "alloc": BuiltinSig(["Int"], "Int"),
    "free": BuiltinSig(["Int"], "Void"),
    "await_result": BuiltinSig(["Any"], "Any"),
    "astra_async_create": BuiltinSig(["Any"], "Int"),
    "astra_async_complete": BuiltinSig(["Int"], "Void"),
    "list_new": BuiltinSig([], "Any"),
    "list_push": BuiltinSig(["Any", "Any"], "Int"),
    "list_get": BuiltinSig(["Any", "Int"], "Any"),
    "list_set": BuiltinSig(["Any", "Int", "Any"], "Int"),
    "list_len": BuiltinSig(["Any"], "Int"),
    "map_new": BuiltinSig([], "Any"),
    "map_has": BuiltinSig(["Any", "Any"], "Bool"),
    "map_get": BuiltinSig(["Any", "Any"], "Any"),
    "map_set": BuiltinSig(["Any", "Any", "Any"], "Int"),
    "file_exists": BuiltinSig(["String"], "Bool"),
    "file_remove": BuiltinSig(["String"], "Int"),
    "tcp_connect": BuiltinSig(["String"], "Int"),
    "tcp_send": BuiltinSig(["Int", "String"], "Int"),
    "tcp_recv": BuiltinSig(["Int", "Int"], "String"),
    "tcp_close": BuiltinSig(["Int"], "Int"),
    "to_json": BuiltinSig(["Any"], "String"),
    "from_json": BuiltinSig(["String"], "Any"),
    "sha256": BuiltinSig(["String"], "String"),
    "hmac_sha256": BuiltinSig(["String", "String"], "String"),
    "proc_exit": BuiltinSig(["Int"], "Never"),
    "env_get": BuiltinSig(["String"], "String"),
    "cwd": BuiltinSig([], "String"),
    "proc_run": BuiltinSig(["String"], "Int"),
    "now_unix": BuiltinSig([], "Int"),
    "monotonic_ms": BuiltinSig([], "Int"),
    "sleep_ms": BuiltinSig(["Int"], "Int"),
    "panic": BuiltinSig(["&str"], "Never"),
    "countOnes": BuiltinSig(["Any"], "Int"),
    "leadingZeros": BuiltinSig(["Any"], "Int"),
    "trailingZeros": BuiltinSig(["Any"], "Int"),
    "popcnt": BuiltinSig(["Any"], "Int"),
    "clz": BuiltinSig(["Any"], "Int"),
    "ctz": BuiltinSig(["Any"], "Int"),
    "rotl": BuiltinSig(["Any", "Any"], "Any"),
    "rotr": BuiltinSig(["Any", "Any"], "Any"),
    "vec_new": BuiltinSig([], "Any"),
    "vec_from": BuiltinSig(["Any"], "Any"),
    "vec_len": BuiltinSig(["Any"], "Int"),
    "vec_get": BuiltinSig(["Any", "Int"], "Any"),
    "vec_set": BuiltinSig(["Any", "Int", "Any"], "Int"),
    "vec_push": BuiltinSig(["Any", "Any"], "Int"),
}

for _name, _sig in list(BUILTIN_SIGS.items()):
    if _name.startswith("__"):
        continue
    if _name in {"print", "len", "read_file", "write_file", "args", "arg", "spawn", "join", "alloc", "free", "await_result", "astra_async_create", "astra_async_complete"}:
        continue
    BUILTIN_SIGS[f"__{_name}"] = _sig
    if _sig.ret != "Void":
        BUILTIN_SIGS[f"__async_{_name}"] = BuiltinSig(_sig.args, "Int")


_FREESTANDING_FORBIDDEN_BUILTINS: set[str] = {
    "print",
    "len",
    "read_file",
    "write_file",
    "args",
    "arg",
    "spawn",
    "join",
    "alloc",
    "free",
    "list_new",
    "list_push",
    "list_get",
    "list_set",
    "list_len",
    "map_new",
    "map_has",
    "map_get",
    "map_set",
    "file_exists",
    "file_remove",
    "tcp_connect",
    "tcp_send",
    "tcp_recv",
    "tcp_close",
    "to_json",
    "from_json",
    "sha256",
    "hmac_sha256",
    "env_get",
    "cwd",
    "proc_run",
    "now_unix",
    "monotonic_ms",
    "sleep_ms",
    "panic",
    "proc_exit",
}
_FREESTANDING_MODE_STACK: list[bool] = []


def _builtin_base_name(name: str) -> str:
    return name[2:] if name.startswith("__") else name


def _freestanding_mode_enabled() -> bool:
    return bool(_FREESTANDING_MODE_STACK and _FREESTANDING_MODE_STACK[-1])


def _require_freestanding_builtin_allowed(name: str, filename: str, line: int, col: int) -> None:
    if not _freestanding_mode_enabled():
        return
    base = _builtin_base_name(name)
    if base in _FREESTANDING_FORBIDDEN_BUILTINS:
        raise SemanticError(_diag(filename, line, col, f"freestanding mode forbids builtin {base}"))


class _OwnedState:
    def __init__(self):
        self.owners: dict[str, str] = {}

    def copy(self):
        nxt = _OwnedState()
        nxt.owners = self.owners.copy()
        return nxt

    def track_alloc(self, name: str):
        self.owners[name] = "alive"

    def move(self, src: str, dst: str, span: Span):
        self._require_alive(src, span)
        self.owners[src] = "moved"
        self.owners[dst] = "alive"

    def free(self, name: str, span: Span):
        self._require_alive(name, span)
        self.owners[name] = "freed"

    def invalidate(self, name: str):
        if name in self.owners and self.owners[name] == "alive":
            self.owners[name] = "moved"

    def assign_name(self, dst: str, src: str, span: Span):
        if src in self.owners:
            self.move(src, dst, span)
            return
        if dst in self.owners:
            self._require_reassigned_after_drop(dst, span)

    def check_use(self, name: str, span: Span):
        if name in self.owners:
            self._require_alive(name, span)

    def check_no_live_leaks(self, fn_name: str, filename: str, line: int, col: int):
        leaked = sorted(k for k, v in self.owners.items() if v == "alive")
        if leaked:
            raise SemanticError(_diag(filename, line, col, f"owned allocation(s) not released in {fn_name}: {', '.join(leaked)}"))

    def merge(self, left: "_OwnedState", right: "_OwnedState"):
        merged: dict[str, str] = {}
        keys = set(left.owners) | set(right.owners)
        for k in keys:
            lv = left.owners.get(k)
            rv = right.owners.get(k)
            if lv == rv:
                merged[k] = lv
            elif "alive" in {lv, rv}:
                merged[k] = "alive"
            elif "freed" in {lv, rv}:
                merged[k] = "freed"
            else:
                merged[k] = "moved"
        self.owners = merged

    def _require_alive(self, name: str, span: Span):
        st = self.owners.get(name)
        if st == "freed":
            raise SemanticError(_diag(span.filename, span.line, span.col, f"use-after-free of {name}"))
        if st == "moved":
            raise SemanticError(_diag(span.filename, span.line, span.col, f"use-after-move of {name}"))

    def _require_reassigned_after_drop(self, name: str, span: Span):
        st = self.owners.get(name)
        if st == "alive":
            raise SemanticError(
                _diag(span.filename, span.line, span.col, f"reassignment would leak owned allocation in {name}; free or move it first")
            )


@dataclass
class _BorrowInfo:
    owner: str
    mutable: bool


class _BorrowState:
    def __init__(self):
        self.shared_counts: dict[str, int] = {}
        self.mutable_borrowed: set[str] = set()
        self.ref_bindings: dict[str, _BorrowInfo] = {}
        self.ref_origins: dict[str, str] = {}

    def copy(self):
        nxt = _BorrowState()
        nxt.shared_counts = self.shared_counts.copy()
        nxt.mutable_borrowed = self.mutable_borrowed.copy()
        nxt.ref_bindings = self.ref_bindings.copy()
        nxt.ref_origins = self.ref_origins.copy()
        return nxt

    def merge(self, left: "_BorrowState", right: "_BorrowState"):
        merged_shared: dict[str, int] = {}
        for owner in set(left.shared_counts) | set(right.shared_counts):
            merged_shared[owner] = max(left.shared_counts.get(owner, 0), right.shared_counts.get(owner, 0))
        self.shared_counts = {k: v for k, v in merged_shared.items() if v > 0}
        self.mutable_borrowed = left.mutable_borrowed | right.mutable_borrowed
        merged_refs: dict[str, _BorrowInfo] = {}
        for name in set(left.ref_bindings) & set(right.ref_bindings):
            li = left.ref_bindings[name]
            ri = right.ref_bindings[name]
            if li.owner == ri.owner and li.mutable == ri.mutable:
                merged_refs[name] = li
        self.ref_bindings = merged_refs
        merged_origins: dict[str, str] = {}
        for name in set(left.ref_origins) & set(right.ref_origins):
            lo = left.ref_origins[name]
            ro = right.ref_origins[name]
            if lo == ro:
                merged_origins[name] = lo
        self.ref_origins = merged_origins

    def release_scope(self, names: set[str]):
        for name in names:
            self.release_ref(name)
            self.ref_origins.pop(name, None)

    def release_ref(self, name: str):
        info = self.ref_bindings.pop(name, None)
        self.ref_origins.pop(name, None)
        if info is None:
            return
        if info.mutable:
            self.mutable_borrowed.discard(info.owner)
            return
        cur = self.shared_counts.get(info.owner, 0)
        if cur <= 1:
            self.shared_counts.pop(info.owner, None)
        else:
            self.shared_counts[info.owner] = cur - 1

    def bind_ref(
        self,
        ref_name: str,
        owner: str,
        mutable: bool,
        fixed: bool,
        filename: str,
        line: int,
        col: int,
        origin: str | None = None,
    ):
        self.release_ref(ref_name)
        self.ensure_can_borrow(owner, mutable, fixed, filename, line, col)
        if mutable:
            self.mutable_borrowed.add(owner)
        else:
            self.shared_counts[owner] = self.shared_counts.get(owner, 0) + 1
        self.ref_bindings[ref_name] = _BorrowInfo(owner, mutable)
        if origin is not None:
            self.ref_origins[ref_name] = origin

    def ensure_can_borrow(self, owner: str, mutable: bool, fixed: bool, filename: str, line: int, col: int):
        has_shared = self.shared_counts.get(owner, 0) > 0
        has_mut = owner in self.mutable_borrowed
        if mutable:
            if fixed:
                raise SemanticError(_diag(filename, line, col, f"cannot mutably borrow fixed binding {owner}"))
            if has_mut or has_shared:
                raise SemanticError(_diag(filename, line, col, f"cannot mutably borrow {owner} while it is already borrowed"))
            return
        if has_mut:
            raise SemanticError(_diag(filename, line, col, f"cannot immutably borrow {owner} while it is mutably borrowed"))

    def check_read(self, name: str, filename: str, line: int, col: int):
        if name in self.ref_bindings:
            return
        if name in self.mutable_borrowed:
            raise SemanticError(_diag(filename, line, col, f"cannot use {name} while it is mutably borrowed"))

    def check_write(self, name: str, filename: str, line: int, col: int):
        if self.shared_counts.get(name, 0) > 0:
            raise SemanticError(_diag(filename, line, col, f"cannot mutate {name} while it is immutably borrowed"))
        if name in self.mutable_borrowed:
            raise SemanticError(_diag(filename, line, col, f"cannot mutate {name} while it is mutably borrowed"))


class _MoveState:
    def __init__(self):
        self.moved: dict[str, bool] = {}

    def copy(self):
        nxt = _MoveState()
        nxt.moved = self.moved.copy()
        return nxt

    def merge(self, left: "_MoveState", right: "_MoveState"):
        merged: dict[str, bool] = {}
        for name in set(left.moved) | set(right.moved):
            merged[name] = left.moved.get(name, False) or right.moved.get(name, False)
        self.moved = merged

    def release_scope(self, scope_prev: dict[str, bool | None]):
        for name, prev in scope_prev.items():
            if prev is None:
                self.moved.pop(name, None)
            else:
                self.moved[name] = prev

    def declare(self, name: str):
        self.moved[name] = False

    def reinitialize(self, name: str):
        if name in self.moved:
            self.moved[name] = False

    def consume(self, name: str, filename: str, line: int, col: int):
        if self.moved.get(name, False):
            raise SemanticError(_diag(filename, line, col, f"use-after-move of {name}"))
        self.moved[name] = True

    def check_use(self, name: str, filename: str, line: int, col: int):
        if self.moved.get(name, False):
            raise SemanticError(_diag(filename, line, col, f"use-after-move of {name}"))


def _assign_base_name(target: Any) -> str | None:
    cur = target
    while isinstance(cur, (FieldExpr, ModuleAccessExpr, IndexExpr)):
        cur = cur.obj
    if isinstance(cur, Name):
        return cur.value
    return None


def _same_type(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    if actual == "Never":
        return True
    expected = _canonical_type(expected)
    actual = _canonical_type(actual)
    if expected == actual:
        return True
    if expected.startswith("&") and not expected.startswith("&mut ") and actual.startswith("&mut "):
        return _same_type(expected[1:], actual[5:])
    if _is_option_type(expected) and _is_option_type(actual):
        return _same_type(_option_inner(expected), _option_inner(actual))
    if _is_option_type(expected) and not _is_option_type(actual):
        return _same_type(_option_inner(expected), actual)
    if {expected, actual} == {"String", "str"}:
        return True
    if expected == "&str" and actual in {"String", "str", "&str"}:
        return True
    if actual == "&str" and expected in {"String", "str", "&str"}:
        return True
    if expected == "Any":
        return True
    if actual == "Any":
        return False
    if expected in {"Float"} | FLOAT_TYPES and _is_int_type(actual):
        return True
    if expected == "Int" and _is_int_type(actual):
        return True
    if actual == "Int" and _is_int_type(expected):
        return True
    return False


def _require_type(filename: str, line: int, col: int, expected: str, actual: str, what: str):
    if actual == NONE_LIT_TYPE:
        if _is_option_type(expected):
            return
        raise SemanticError(_diag(filename, line, col, f"`none` requires Option<T> context for {what}, got {expected}"))
    if not _same_type(expected, actual):
        exp = _canonical_type(expected)
        act = _canonical_type(actual)
        if _is_int_type(exp) and _is_int_type(act):
            raise SemanticError(_diag(filename, line, col, f"cannot implicitly convert {act} to {exp}, use explicit cast"))
        raise SemanticError(_diag(filename, line, col, f"type mismatch for {what}: expected {expected}, got {actual}"))


def _require_sized_value_type(filename: str, line: int, col: int, typ: str, what: str):
    if _is_ref_type(typ):
        return
    if _is_unsized_value_type(typ):
        raise SemanticError(_diag(filename, line, col, f"unsized type {typ} is not allowed by value for {what}; use & or &mut"))


def _require_strict_int_operands(filename: str, line: int, col: int, op: str, left: str, right: str):
    l = _canonical_type(left)
    r = _canonical_type(right)
    if not _is_int_type(l) or not _is_int_type(r):
        raise SemanticError(_diag(filename, line, col, f"operator {op} expects integer operands, got {left} and {right}"))
    if l != r:
        raise SemanticError(_diag(filename, line, col, f"operator {op} requires matching integer types, got {left} and {right}"))


def _cast_supported(src: str, dst: str) -> bool:
    src_c = _canonical_type(src)
    dst_c = _canonical_type(dst)
    if _is_numeric_scalar_type(src_c) and _is_numeric_scalar_type(dst_c):
        return True
    if src_c == "Bool" and (_is_numeric_scalar_type(dst_c) or dst_c == "Bool"):
        return True
    if dst_c == "Bool" and (_is_numeric_scalar_type(src_c) or src_c == "Bool"):
        return True
    if src_c == "Any":
        return _is_any_dynamic_cast_target(dst_c)
    if dst_c == "Any":
        return _is_any_dynamic_cast_target(src_c) or _is_ref_type(src_c) or src_c.startswith("fn(")
    return False


def _is_any_dynamic_cast_target(typ: str) -> bool:
    c = _canonical_type(typ)
    return (
        c in {"Bool", "String", "str"}
        or _is_numeric_scalar_type(c)
        or _is_ref_type(c)
        or _is_option_type(c)
        or _is_vec_type(c)
        or _is_slice_type(c)
        or c.startswith("fn(")
        or c.startswith("unsafe fn(")
    )


def _int_cast_bounds(bits: int, signed: bool) -> tuple[int, int]:
    if signed:
        return -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return 0, (1 << bits) - 1


def _saturating_float_to_int(value: float, bits: int, signed: bool) -> int:
    if math.isnan(value):
        return 0
    lo, hi = _int_cast_bounds(bits, signed)
    if value == float("inf"):
        return hi
    if value == float("-inf"):
        return lo if signed else 0
    v = math.trunc(value)
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _const_int_expr_value(expr: Any) -> int | None:
    if isinstance(expr, Literal) and isinstance(expr.value, int) and not isinstance(expr.value, bool):
        return int(expr.value)
    if isinstance(expr, Unary) and expr.op == "-":
        inner = _const_int_expr_value(expr.expr)
        if inner is not None:
            return -inner
    if isinstance(expr, CastExpr):
        return _const_int_expr_value(expr.expr)
    return None


def _require_shift_rhs_static_safe(filename: str, op: str, lhs_ty: str, rhs_expr: Any) -> None:
    info = _int_info(lhs_ty)
    if info is None:
        return
    bits, _ = info
    v = _const_int_expr_value(rhs_expr)
    if v is None:
        return
    if v < 0 or v >= bits:
        raise SemanticError(
            _diag(
                filename,
                getattr(rhs_expr, "line", 0),
                getattr(rhs_expr, "col", 0),
                f"shift count {v} out of range for {lhs_ty} in {op}; expected 0..{bits - 1}",
            )
        )


def _require_compound_assign_compat(filename: str, line: int, col: int, op: str, lhs: str, rhs: str):
    if op == "=":
        _require_type(filename, line, col, lhs, rhs, "assignment")
        return
    _require_type(filename, line, col, lhs, rhs, "assignment")
    bop = op[:-1]
    lc = _canonical_type(lhs)
    rc = _canonical_type(rhs)
    if bop in {"+", "-", "*", "/", "%"}:
        if _is_int_type(lc) and _is_int_type(rc):
            _require_strict_int_operands(filename, line, col, bop, lhs, rhs)
            return
        if _is_float_type(lc) and _is_float_type(rc):
            return
        if bop == "+" and _is_text_type(lc) and _is_text_type(rc):
            return
        raise SemanticError(_diag(filename, line, col, f"operator {op} requires matching numeric types; use explicit cast"))
    if bop in {"&", "|", "^", "<<", ">>"}:
        _require_strict_int_operands(filename, line, col, bop, lhs, rhs)
        return
    raise SemanticError(_diag(filename, line, col, f"unsupported assignment operator {op}"))


def _consume_if_move_name(expr: Any, expr_ty: str, move: _MoveState, filename: str, line: int, col: int):
    if isinstance(expr, Name) and not _is_copy_type(expr_ty):
        move.consume(expr.value, filename, line, col)


def _ref_return_tied_to_param(expr: Any, ref_param_names: set[str], borrow: _BorrowState) -> bool:
    if isinstance(expr, Name):
        if expr.value in ref_param_names:
            return True
        origin = borrow.ref_origins.get(expr.value)
        if origin in ref_param_names:
            return True
        info = borrow.ref_bindings.get(expr.value)
        return info is not None and info.owner in ref_param_names
    return False


def _lookup(name: str, scopes: list[dict[str, str]]) -> str | None:
    # Handle qualified names (module::symbol)
    if "::" in name:
        parts = name.split("::", 1)
        module_name, symbol_name = parts
        
        # First, look up the module itself
        module_type = None
        for scope in reversed(scopes):
            if module_name in scope:
                module_type = scope[module_name]
                break
        
        if module_type is None:
            return None
        
        # If it's a module, check if we have the qualified symbol
        qualified_name = name
        for scope in reversed(scopes):
            if qualified_name in scope:
                return scope[qualified_name]
        return None
    
    # Regular name lookup
    for scope in reversed(scopes):
        if name in scope:
            return scope[name]
    return None


def _assign(name: str, typ: str, scopes: list[dict[str, str]], filename: str, line: int, col: int):
    for scope in reversed(scopes):
        if name in scope:
            scope[name] = typ
            return
    raise SemanticError(_diag(filename, line, col, f"assignment to undefined name {name}"))


def _lookup_fixed(name: str, fixed_scopes: list[dict[str, bool]]) -> bool | None:
    for scope in reversed(fixed_scopes):
        if name in scope:
            return scope[name]
    return None


def _is_typevar(name: str, known_types: set[str]) -> bool:
    c = _canonical_type(name)
    if c in known_types:
        return False
    if c in {"String", "str", "Bool", "Any", "Void", "Never", "Bytes"}:
        return False
    if is_int_type_name(c):
        return False
    if _is_float_type(c):
        return False
    if any(ch in c for ch in "<>[]&(), "):
        return False
    return bool(c)


def _split_top_level(text: str, sep: str) -> list[str]:
    out: list[str] = []
    depth_angle = 0
    depth_paren = 0
    depth_bracket = 0
    cur: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "<":
            depth_angle += 1
        elif ch == ">" and depth_angle > 0:
            depth_angle -= 1
        elif ch == "(":
            depth_paren += 1
        elif ch == ")" and depth_paren > 0:
            depth_paren -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]" and depth_bracket > 0:
            depth_bracket -= 1
        if (
            text.startswith(sep, i)
            and depth_angle == 0
            and depth_paren == 0
            and depth_bracket == 0
        ):
            out.append("".join(cur).strip())
            cur = []
            i += len(sep)
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur).strip())
    return out


def _parse_fn_type(typ: str) -> tuple[list[str], str, bool] | None:
    t = typ.strip()
    unsafe = False
    if t.startswith("unsafe "):
        unsafe = True
        t = t[7:].lstrip()
    if not t.startswith("fn("):
        return None
    depth = 0
    close = -1
    for i, ch in enumerate(t):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                close = i
                break
    if close < 0 or depth != 0:
        return None
    if close + 4 > len(t) or t[close + 1 : close + 5] != " -> ":
        return None
    params_text = t[3:close].strip()
    ret = t[close + 5 :].strip()
    if not ret:
        return None
    if not params_text:
        return [], ret, unsafe
    return _split_top_level(params_text, ","), ret, unsafe


def _fn_type(params: list[tuple[str, str]], ret: str, *, unsafe: bool = False) -> str:
    head = "unsafe fn" if unsafe else "fn"
    return f"{head}({', '.join(ty for _, ty in params)}) -> {ret}"


def _is_send_type(
    typ: str,
    structs: dict[str, StructDecl],
    *,
    seen: set[str] | None = None,
) -> bool:
    c = _canonical_type(typ)
    if c in {"Never", "Void"}:
        return True
    if c == "Any":
        return False
    if c.startswith("&mut "):
        return False
    if c.startswith("&"):
        return _is_sync_type(c[1:], structs, seen=seen)
    if c.startswith("fn(") or c.startswith("unsafe fn("):
        return True
    if _is_option_type(c):
        return _is_send_type(_option_inner(c), structs, seen=seen)
    if _is_vec_type(c):
        return _is_send_type(_vec_inner(c), structs, seen=seen)
    if _is_slice_type(c):
        return False
    if _is_numeric_scalar_type(c) or c in {"Bool", "String", "str"}:
        return True
    if c in structs:
        guard = seen or set()
        if c in guard:
            return True
        guard.add(c)
        for _, fty in structs[c].fields:
            if not _is_send_type(fty, structs, seen=guard):
                return False
        guard.remove(c)
        return True
    return False


def _is_sync_type(
    typ: str,
    structs: dict[str, StructDecl],
    *,
    seen: set[str] | None = None,
) -> bool:
    c = _canonical_type(typ)
    if c in {"Never", "Void"}:
        return True
    if c == "Any":
        return False
    if c.startswith("&mut "):
        return False
    if c.startswith("&"):
        return _is_sync_type(c[1:], structs, seen=seen)
    if c.startswith("fn(") or c.startswith("unsafe fn("):
        return True
    if _is_option_type(c):
        return _is_sync_type(_option_inner(c), structs, seen=seen)
    if _is_vec_type(c):
        # Vec<T> is mutable by design and not Sync without synchronization.
        return False
    if _is_slice_type(c):
        return _is_sync_type(_slice_inner(c), structs, seen=seen)
    if _is_numeric_scalar_type(c) or c in {"Bool", "String", "str"}:
        return True
    if c in structs:
        guard = seen or set()
        if c in guard:
            return True
        guard.add(c)
        for _, fty in structs[c].fields:
            if not _is_sync_type(fty, structs, seen=guard):
                return False
        guard.remove(c)
        return True
    return False


def _require_send(
    typ: str,
    structs: dict[str, StructDecl],
    filename: str,
    line: int,
    col: int,
    context: str,
) -> None:
    if not _is_send_type(typ, structs):
        raise SemanticError(_diag(filename, line, col, f"{context} requires Send, got {typ}"))


def _require_sync(
    typ: str,
    structs: dict[str, StructDecl],
    filename: str,
    line: int,
    col: int,
    context: str,
) -> None:
    if not _is_sync_type(typ, structs):
        raise SemanticError(_diag(filename, line, col, f"{context} requires Sync, got {typ}"))


def _typed(node: Any, typ: str) -> str:
    setattr(node, "inferred_type", typ)
    return typ


def _specialization_score(
    decl: FnDecl | ExternFnDecl,
    arg_types: list[str],
    known_types: set[str],
) -> tuple[int, int, int, int] | None:
    if len(decl.params) != len(arg_types):
        return None
    type_vars = set(getattr(decl, "generics", []))
    for _, pty in decl.params:
        if _is_typevar(pty, known_types):
            type_vars.add(pty)
    bindings: dict[str, str] = {}
    exact = 0
    constrained = 0
    wildcards = 0
    for (_, pty), aty in zip(decl.params, arg_types):
        if pty in type_vars:
            bound = bindings.get(pty)
            if bound is None:
                bindings[pty] = aty
            elif not _same_type(bound, aty):
                return None
            wildcards += 1
            continue
        if pty == "Any":
            wildcards += 1
            continue
        if not _same_type(pty, aty):
            return None
        constrained += 1
        if pty == aty:
            exact += 1
    impl_bonus = 1 if getattr(decl, "is_impl", False) else 0
    return (exact, constrained, -wildcards, impl_bonus)


def _choose_impl(
    name: str,
    decls: list[FnDecl | ExternFnDecl],
    arg_types: list[str],
    known_types: set[str],
    filename: str,
    line: int,
    col: int,
) -> FnDecl | ExternFnDecl:
    ranked: list[tuple[tuple[int, int, int, int], FnDecl | ExternFnDecl]] = []
    for d in decls:
        sc = _specialization_score(d, arg_types, known_types)
        if sc is not None:
            ranked.append((sc, d))
    if not ranked:
        raise SemanticError(_diag(filename, line, col, f"no matching impl for {name}({', '.join(arg_types)})"))
    ranked.sort(key=lambda x: x[0], reverse=True)
    best_score = ranked[0][0]
    best = [d for s, d in ranked if s == best_score]
    if len(best) > 1:
        raise SemanticError(_diag(filename, line, col, f"ambiguous impl for {name}({', '.join(arg_types)})"))
    return best[0]


def analyze(
    prog: Program,
    filename: str = "<input>",
    freestanding: bool = False,
    *,
    collect_errors: bool = False,
):
    _FREESTANDING_MODE_STACK.append(freestanding)
    try:
        errors: list[str] = []
        seen_errors: set[str] = set()

        def _record(err: SemanticError) -> None:
            if not collect_errors:
                raise err
            for line in str(err).splitlines():
                if line in seen_errors:
                    continue
                seen_errors.add(line)
                errors.append(line)

        fn_groups: dict[str, list[FnDecl | ExternFnDecl]] = {}
        structs: dict[str, StructDecl] = {}
        enums: dict[str, EnumDecl] = {}
        global_scope: dict[str, str] = {}
        for item in prog.items:
            try:
                if isinstance(item, ImportDecl):
                    try:
                        resolved_path = resolve_import_path(item, filename)
                    except ModuleResolutionError as err:
                        raise SemanticError(_diag(filename, item.line, item.col, str(err))) from err
                    
                    # Load symbols from the imported module
                    try:
                        imported_symbols = get_imported_symbols(item, filename)
                    except Exception as e:
                        # If symbol loading fails, continue with empty symbols
                        # This allows the compiler to continue with other errors
                        imported_symbols = {}
                    
                    if item.alias:
                        # Import with alias: add all symbols under the alias namespace
                        # Check for collision with existing symbols
                        if item.alias in global_scope:
                            raise SemanticError(_diag(filename, item.line, item.col, f"import alias '{item.alias}' collides with existing symbol"))
                        
                        for symbol_name, symbol_decl in imported_symbols.items():
                            qualified_name = f"{item.alias}::{symbol_name}"
                            # Check for collision with existing symbols
                            if qualified_name in global_scope:
                                raise SemanticError(_diag(filename, item.line, item.col, f"imported symbol '{qualified_name}' collides with existing symbol"))
                            
                            # Store the actual type information
                            if isinstance(symbol_decl, (FnDecl, ExternFnDecl)):
                                global_scope[qualified_name] = f"fn({', '.join(t for _, t in symbol_decl.params)}) -> {symbol_decl.ret}"
                            elif isinstance(symbol_decl, StructDecl):
                                global_scope[qualified_name] = symbol_decl.name
                                structs[qualified_name] = symbol_decl  # Add to structs dict for type checking
                            elif isinstance(symbol_decl, EnumDecl):
                                global_scope[qualified_name] = symbol_decl.name
                                enums[qualified_name] = symbol_decl  # Add to enums dict for type checking
                            elif isinstance(symbol_decl, TypeAliasDecl):
                                global_scope[qualified_name] = symbol_decl.target
                        # Also add the module itself for qualified access
                        global_scope[item.alias] = f"module:{resolved_path}"
                    else:
                        # Import without alias: add symbols directly to global scope
                        # Check for collision with existing symbols
                        module_name = item.path[-1] if item.path else Path(item.source).stem
                        if module_name in global_scope:
                            raise SemanticError(_diag(filename, item.line, item.col, f"import module '{module_name}' collides with existing symbol"))
                        
                        for symbol_name, symbol_decl in imported_symbols.items():
                            # Check for collision with existing symbols
                            if symbol_name in global_scope:
                                raise SemanticError(_diag(filename, item.line, item.col, f"imported symbol '{symbol_name}' collides with existing symbol"))
                            
                            # Store the actual type information
                            if isinstance(symbol_decl, (FnDecl, ExternFnDecl)):
                                global_scope[symbol_name] = f"fn({', '.join(t for _, t in symbol_decl.params)}) -> {symbol_decl.ret}"
                            elif isinstance(symbol_decl, StructDecl):
                                global_scope[symbol_name] = symbol_decl.name
                                structs[symbol_name] = symbol_decl  # Add to structs dict for type checking
                            elif isinstance(symbol_decl, EnumDecl):
                                global_scope[symbol_name] = symbol_decl.name
                                enums[symbol_name] = symbol_decl  # Add to enums dict for type checking
                            elif isinstance(symbol_decl, TypeAliasDecl):
                                global_scope[symbol_name] = symbol_decl.target
                        # Add the last path component as module name for qualified access
                        global_scope[module_name] = f"module:{resolved_path}"
                    continue
                if isinstance(item, StructDecl):
                    for _, field_ty in item.fields:
                        _validate_decl_type(field_ty, filename, item.line, item.col)
                    if item.packed:
                        for _, field_ty in item.fields:
                            c = _canonical_type(field_ty)
                            if c != "Bool" and not _is_int_type(c):
                                raise SemanticError(_diag(filename, item.line, item.col, "packed struct fields must be integer or bool types"))
                    structs[item.name] = item
                    continue
                if isinstance(item, TypeAliasDecl):
                    _validate_decl_type(item.target, filename, item.line, item.col)
                    continue
                if isinstance(item, EnumDecl):
                    enums[item.name] = item
                    continue
                if isinstance(item, (FnDecl, ExternFnDecl)):
                    for _, pty in item.params:
                        _validate_decl_type(pty, filename, item.line, item.col)
                    _validate_decl_type(item.ret, filename, item.line, item.col)
                    fn_groups.setdefault(item.name, []).append(item)
            except SemanticError as err:
                _record(err)
                continue

        for name, decls in fn_groups.items():
            if len(decls) == 1 and not (isinstance(decls[0], FnDecl) and decls[0].is_impl):
                if isinstance(decls[0], FnDecl):
                    decls[0].symbol = name
                continue
            for i, d in enumerate(decls):
                if isinstance(d, FnDecl):
                    d.symbol = f"{name}__impl{i}"

        if not freestanding:
            try:
                mains = [d for d in fn_groups.get("main", []) if isinstance(d, FnDecl)]
                if not mains:
                    raise SemanticError(_diag(filename, 1, 1, "missing main()"))
                if len(mains) != 1:
                    raise SemanticError(_diag(filename, mains[0].line, mains[0].col, "main() must have a single unambiguous impl"))
                if mains[0].is_impl:
                    raise SemanticError(_diag(filename, mains[0].line, mains[0].col, "main() cannot be declared with impl"))
            except SemanticError as err:
                _record(err)

        for decls in fn_groups.values():
            for fn in decls:
                if isinstance(fn, ExternFnDecl):
                    continue
                try:
                    _analyze_fn(fn, fn_groups, structs, enums, filename, global_scope)
                except SemanticError as err:
                    _record(err)
                    continue
        if errors:
            raise SemanticError("\n".join(errors))
    finally:
        _FREESTANDING_MODE_STACK.pop()


def _analyze_fn(
    fn: FnDecl,
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    filename: str,
    global_scope: dict[str, str],
):
    for pname, pty in fn.params:
        _require_sized_value_type(filename, fn.line, fn.col, pty, f"parameter {pname}")
    _require_sized_value_type(filename, fn.line, fn.col, fn.ret, "function return")
    ref_param_names = {pname for pname, pty in fn.params if _is_ref_type(pty)}
    if _is_ref_type(fn.ret) and not ref_param_names:
        raise SemanticError(_diag(filename, fn.line, fn.col, f"function {fn.name} returns a reference but has no reference parameter to tie its lifetime"))
    scopes: list[dict[str, str]] = [global_scope, {n: t for n, t in fn.params}]
    fixed_scopes: list[dict[str, bool]] = [{n: False for n, _ in fn.params}]
    owned = _OwnedState()
    borrow = _BorrowState()
    move = _MoveState()
    for n, _ in fn.params:
        move.declare(n)
    borrow_scopes: list[set[str]] = [set()]
    move_scopes: list[dict[str, bool | None]] = [{}]
    _check_block(
        fn.body,
        scopes,
        fixed_scopes,
        borrow_scopes,
        move_scopes,
        fn_groups,
        structs,
        enums,
        fn.ret,
        ref_param_names,
        owned,
        borrow,
        move,
        filename,
        fn.name,
        0,
        fn.unsafe,
    )
    owned.check_no_live_leaks(fn.name, filename, fn.line, fn.col)


def _check_block(
    body: list[Any],
    scopes: list[dict[str, str]],
    fixed_scopes: list[dict[str, bool]],
    borrow_scopes: list[set[str]],
    move_scopes: list[dict[str, bool | None]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    fn_ret: str,
    ref_param_names: set[str],
    owned: _OwnedState,
    borrow: _BorrowState,
    move: _MoveState,
    filename: str,
    fn_name: str,
    loop_depth: int,
    unsafe_ok: bool,
):
    for st in body:
        _check_stmt(
            st,
            scopes,
            fixed_scopes,
            borrow_scopes,
            move_scopes,
            fn_groups,
            structs,
            enums,
            fn_ret,
            ref_param_names,
            owned,
            borrow,
            move,
            filename,
            fn_name,
            loop_depth,
            unsafe_ok,
        )
    borrow.release_scope(borrow_scopes[-1])
    move.release_scope(move_scopes[-1])


def _check_stmt(
    st,
    scopes: list[dict[str, str]],
    fixed_scopes: list[dict[str, bool]],
    borrow_scopes: list[set[str]],
    move_scopes: list[dict[str, bool | None]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    fn_ret: str,
    ref_param_names: set[str],
    owned: _OwnedState,
    borrow: _BorrowState,
    move: _MoveState,
    filename: str,
    fn_name: str,
    loop_depth: int,
    unsafe_ok: bool,
):
    if isinstance(st, LetStmt):
        ty = _infer(st.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        if ty == NONE_LIT_TYPE and st.type_name is None:
            raise SemanticError(_diag(filename, st.line, st.col, f"`none` requires explicit Option<T> type for {st.name}"))
        if st.type_name is not None:
            _require_type(filename, st.line, st.col, st.type_name, ty, st.name)
            ty = st.type_name
        _require_sized_value_type(filename, st.line, st.col, ty, st.name)
        if st.name in scopes[-1]:
            borrow.release_ref(st.name)
        if st.name not in move_scopes[-1]:
            move_scopes[-1][st.name] = move.moved.get(st.name)
        move.declare(st.name)
        scopes[-1][st.name] = ty
        fixed_scopes[-1][st.name] = st.fixed
        borrow_scopes[-1].add(st.name)
        if _is_ref_type(ty):
            if isinstance(st.expr, Unary) and st.expr.op in {"&", "&mut"} and isinstance(st.expr.expr, Name):
                owner = st.expr.expr.value
                fixed_owner = bool(_lookup_fixed(owner, fixed_scopes))
                borrow.bind_ref(st.name, owner, st.expr.op == "&mut", fixed_owner, filename, st.line, st.col)
            elif isinstance(st.expr, Name):
                src_ref = borrow.ref_bindings.get(st.expr.value)
                if src_ref is not None:
                    if src_ref.mutable:
                        raise SemanticError(_diag(filename, st.line, st.col, "cannot copy mutable reference"))
                    fixed_owner = bool(_lookup_fixed(src_ref.owner, fixed_scopes))
                    origin = borrow.ref_origins.get(st.expr.value)
                    borrow.bind_ref(st.name, src_ref.owner, False, fixed_owner, filename, st.line, st.col, origin=origin)
                elif st.expr.value in ref_param_names:
                    borrow.ref_origins[st.name] = st.expr.value
        if isinstance(st.expr, Name):
            owned.assign_name(st.name, st.expr.value, Span.at(filename, st.line, st.col))
        _consume_if_move_name(st.expr, ty, move, filename, st.line, st.col)
        if _is_alloc_call(st.expr):
            owned.track_alloc(st.name)
        return
    if isinstance(st, AssignStmt):
        rhs = _infer(st.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        base = _assign_base_name(st.target)
        if base is not None:
            borrow.check_write(base, filename, st.line, st.col)
        if isinstance(st.target, Name):
            is_fixed = _lookup_fixed(st.target.value, fixed_scopes)
            if is_fixed is None:
                raise SemanticError(_diag(filename, st.line, st.col, f"assignment to undefined name {st.target.value}"))
            if is_fixed:
                raise SemanticError(_diag(filename, st.line, st.col, f"cannot assign to fixed binding {st.target.value}"))
            lhs = _lookup(st.target.value, scopes)
            if lhs is None:
                raise SemanticError(_diag(filename, st.line, st.col, f"assignment to undefined name {st.target.value}"))
            _require_compound_assign_compat(filename, st.line, st.col, st.op, lhs, rhs)
            if st.op in {"<<=", ">>="}:
                _require_shift_rhs_static_safe(filename, st.op, lhs, st.expr)
            if _is_ref_type(lhs):
                if isinstance(st.expr, Unary) and st.expr.op in {"&", "&mut"} and isinstance(st.expr.expr, Name):
                    owner = st.expr.expr.value
                    fixed_owner = bool(_lookup_fixed(owner, fixed_scopes))
                    borrow.bind_ref(st.target.value, owner, st.expr.op == "&mut", fixed_owner, filename, st.line, st.col)
                elif isinstance(st.expr, Name):
                    src_ref = borrow.ref_bindings.get(st.expr.value)
                    if src_ref is not None:
                        if src_ref.mutable:
                            raise SemanticError(_diag(filename, st.line, st.col, "cannot copy mutable reference"))
                        fixed_owner = bool(_lookup_fixed(src_ref.owner, fixed_scopes))
                        origin = borrow.ref_origins.get(st.expr.value)
                        borrow.bind_ref(st.target.value, src_ref.owner, False, fixed_owner, filename, st.line, st.col, origin=origin)
                    else:
                        borrow.release_ref(st.target.value)
                        if st.expr.value in ref_param_names:
                            borrow.ref_origins[st.target.value] = st.expr.value
                else:
                    borrow.release_ref(st.target.value)
            else:
                borrow.release_ref(st.target.value)
            if isinstance(st.expr, Name):
                owned.assign_name(st.target.value, st.expr.value, Span.at(filename, st.line, st.col))
            else:
                owned._require_reassigned_after_drop(st.target.value, Span.at(filename, st.line, st.col))
            _consume_if_move_name(st.expr, rhs, move, filename, st.line, st.col)
            _assign(st.target.value, lhs, scopes, filename, st.line, st.col)
            move.reinitialize(st.target.value)
            return
        lhs = _infer(st.target, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        _require_compound_assign_compat(filename, st.line, st.col, st.op, lhs, rhs)
        if st.op in {"<<=", ">>="}:
            _require_shift_rhs_static_safe(filename, st.op, lhs, st.expr)
        return
    if isinstance(st, ReturnStmt):
        expr_ty = "Void" if st.expr is None else _infer(st.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        _require_type(filename, st.line, st.col, fn_ret, expr_ty, "return")
        if _is_ref_type(fn_ret) and st.expr is not None and not _ref_return_tied_to_param(st.expr, ref_param_names, borrow):
            raise SemanticError(_diag(filename, st.line, st.col, "returned reference is not tied to an input reference parameter"))
        if isinstance(st.expr, Name):
            owned.invalidate(st.expr.value)
        if st.expr is not None:
            _consume_if_move_name(st.expr, expr_ty, move, filename, st.line, st.col)
        return
    if isinstance(st, BreakStmt):
        if loop_depth <= 0:
            raise SemanticError(_diag(filename, st.line, st.col, "break used outside loop"))
        return
    if isinstance(st, ContinueStmt):
        if loop_depth <= 0:
            raise SemanticError(_diag(filename, st.line, st.col, "continue used outside loop"))
        return
    if isinstance(st, DeferStmt):
        _infer(st.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        return
    if isinstance(st, ComptimeStmt):
        _check_block(
            st.body,
            scopes + [{}],
            fixed_scopes + [{}],
            borrow_scopes + [set()],
            move_scopes + [{}],
            fn_groups,
            structs,
            enums,
            fn_ret,
            ref_param_names,
            owned,
            borrow,
            move,
            filename,
            fn_name,
            loop_depth,
            unsafe_ok,
        )
        return
    if isinstance(st, UnsafeStmt):
        _check_block(
            st.body,
            scopes + [{}],
            fixed_scopes + [{}],
            borrow_scopes + [set()],
            move_scopes + [{}],
            fn_groups,
            structs,
            enums,
            fn_ret,
            ref_param_names,
            owned,
            borrow,
            move,
            filename,
            fn_name,
            loop_depth,
            True,
        )
        return
    if isinstance(st, IfStmt):
        cond_ty = _infer(st.cond, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        _require_type(filename, st.line, st.col, "Bool", cond_ty, "if condition")
        then_owned = owned.copy()
        then_scopes = scopes + [{}]
        then_fixed_scopes = fixed_scopes + [{}]
        then_borrow = borrow.copy()
        then_move = move.copy()
        then_borrow_scopes = borrow_scopes + [set()]
        then_move_scopes = move_scopes + [{}]
        _check_block(
            st.then_body,
            then_scopes,
            then_fixed_scopes,
            then_borrow_scopes,
            then_move_scopes,
            fn_groups,
            structs,
            enums,
            fn_ret,
            ref_param_names,
            then_owned,
            then_borrow,
            then_move,
            filename,
            fn_name,
            loop_depth,
            unsafe_ok,
        )
        else_owned = owned.copy()
        else_scopes = scopes + [{}]
        else_fixed_scopes = fixed_scopes + [{}]
        else_borrow = borrow.copy()
        else_move = move.copy()
        else_borrow_scopes = borrow_scopes + [set()]
        else_move_scopes = move_scopes + [{}]
        _check_block(
            st.else_body,
            else_scopes,
            else_fixed_scopes,
            else_borrow_scopes,
            else_move_scopes,
            fn_groups,
            structs,
            enums,
            fn_ret,
            ref_param_names,
            else_owned,
            else_borrow,
            else_move,
            filename,
            fn_name,
            loop_depth,
            unsafe_ok,
        )
        owned.merge(then_owned, else_owned)
        borrow.merge(then_borrow, else_borrow)
        move.merge(then_move, else_move)
        return
    if isinstance(st, WhileStmt):
        cond_ty = _infer(st.cond, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        _require_type(filename, st.line, st.col, "Bool", cond_ty, "while condition")
        loop_owned = owned.copy()
        loop_scopes = scopes + [{}]
        loop_fixed_scopes = fixed_scopes + [{}]
        loop_borrow = borrow.copy()
        loop_move = move.copy()
        loop_borrow_scopes = borrow_scopes + [set()]
        loop_move_scopes = move_scopes + [{}]
        _check_block(
            st.body,
            loop_scopes,
            loop_fixed_scopes,
            loop_borrow_scopes,
            loop_move_scopes,
            fn_groups,
            structs,
            enums,
            fn_ret,
            ref_param_names,
            loop_owned,
            loop_borrow,
            loop_move,
            filename,
            fn_name,
            loop_depth + 1,
            unsafe_ok,
        )
        owned.merge(owned, loop_owned)
        borrow.merge(borrow, loop_borrow)
        move.merge(move, loop_move)
        return
    if isinstance(st, ForStmt):
        loop_scopes = scopes + [{}]
        loop_fixed_scopes = fixed_scopes + [{}]
        loop_owned = owned.copy()
        loop_borrow = borrow.copy()
        loop_move = move.copy()
        loop_borrow_scopes = borrow_scopes + [set()]
        loop_move_scopes = move_scopes + [{}]
        if st.init is not None:
            if isinstance(st.init, LetStmt):
                _check_stmt(
                    st.init,
                    loop_scopes,
                    loop_fixed_scopes,
                    loop_borrow_scopes,
                    loop_move_scopes,
                    fn_groups,
                    structs,
                    enums,
                    fn_ret,
                    ref_param_names,
                    loop_owned,
                    loop_borrow,
                    loop_move,
                    filename,
                    fn_name,
                    loop_depth + 1,
                    unsafe_ok,
                )
            else:
                _infer(st.init, loop_scopes, loop_fixed_scopes, fn_groups, structs, enums, loop_owned, loop_borrow, loop_move, filename, fn_name, unsafe_ok)
        if st.cond is not None:
            cond_ty = _infer(st.cond, loop_scopes, loop_fixed_scopes, fn_groups, structs, enums, loop_owned, loop_borrow, loop_move, filename, fn_name, unsafe_ok)
            _require_type(filename, st.line, st.col, "Bool", cond_ty, "for condition")
        if st.step is not None:
            if isinstance(st.step, AssignStmt):
                _check_stmt(
                    st.step,
                    loop_scopes,
                    loop_fixed_scopes,
                    loop_borrow_scopes,
                    loop_move_scopes,
                    fn_groups,
                    structs,
                    enums,
                    fn_ret,
                    ref_param_names,
                    loop_owned,
                    loop_borrow,
                    loop_move,
                    filename,
                    fn_name,
                    loop_depth + 1,
                    unsafe_ok,
                )
            else:
                _infer(st.step, loop_scopes, loop_fixed_scopes, fn_groups, structs, enums, loop_owned, loop_borrow, loop_move, filename, fn_name, unsafe_ok)
        _check_block(
            st.body,
            loop_scopes,
            loop_fixed_scopes,
            loop_borrow_scopes,
            loop_move_scopes,
            fn_groups,
            structs,
            enums,
            fn_ret,
            ref_param_names,
            loop_owned,
            loop_borrow,
            loop_move,
            filename,
            fn_name,
            loop_depth + 1,
            unsafe_ok,
        )
        owned.merge(owned, loop_owned)
        borrow.merge(borrow, loop_borrow)
        move.merge(move, loop_move)
        return
    if isinstance(st, MatchStmt):
        subject_ty = _infer(st.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        seen_bool: set[bool] = set()
        seen_wildcard = False
        for idx, (pat, body) in enumerate(st.arms):
            if isinstance(pat, WildcardPattern):
                if seen_wildcard:
                    raise SemanticError(_diag(filename, pat.line, pat.col, "duplicate wildcard match arm"))
                if idx != len(st.arms) - 1:
                    raise SemanticError(_diag(filename, pat.line, pat.col, "wildcard match arm must be last"))
                seen_wildcard = True
                pty = subject_ty
            else:
                pty = _infer(pat, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
                if subject_ty != "Any":
                    _require_type(filename, st.line, st.col, subject_ty, pty, "match pattern")
                if isinstance(pat, BoolLit):
                    if pat.value in seen_bool:
                        value_text = "true" if pat.value else "false"
                        raise SemanticError(_diag(filename, pat.line, pat.col, f"duplicate Bool match arm for {value_text}"))
                    seen_bool.add(pat.value)
            arm_scopes = scopes + [{}]
            arm_fixed_scopes = fixed_scopes + [{}]
            arm_borrow_scopes = borrow_scopes + [set()]
            arm_move_scopes = move_scopes + [{}]
            _check_block(
                body,
                arm_scopes,
                arm_fixed_scopes,
                arm_borrow_scopes,
                arm_move_scopes,
                fn_groups,
                structs,
                enums,
                fn_ret,
                ref_param_names,
                owned.copy(),
                borrow.copy(),
                move.copy(),
                filename,
                fn_name,
                loop_depth,
                unsafe_ok,
            )
        if subject_ty == "Bool" and not seen_wildcard and seen_bool != {True, False}:
            raise SemanticError(_diag(filename, st.line, st.col, "non-exhaustive match for Bool"))
        return
    if isinstance(st, ExprStmt):
        _infer(st.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        if _is_free_call(st.expr):
            ptr = st.expr.args[0]
            if not isinstance(ptr, Name):
                raise SemanticError(_diag(filename, st.line, st.col, "free() expects a named owner"))
            owned.free(ptr.value, Span.at(filename, st.line, st.col))
        return
    if isinstance(st, DropStmt):
        expr_ty = _infer(st.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        _consume_if_move_name(st.expr, expr_ty, move, filename, st.line, st.col)
        if isinstance(st.expr, Name):
            if st.expr.value in owned.owners:
                setattr(st, "drop_free", True)
                owned.free(st.expr.value, Span.at(filename, st.line, st.col))
        if _is_free_call(st.expr):
            ptr = st.expr.args[0]
            if not isinstance(ptr, Name):
                raise SemanticError(_diag(filename, st.line, st.col, "free() expects a named owner"))
            owned.free(ptr.value, Span.at(filename, st.line, st.col))
        return


def _infer(
    e,
    scopes: list[dict[str, str]],
    fixed_scopes: list[dict[str, bool]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    owned: _OwnedState | None,
    borrow: _BorrowState,
    move: _MoveState,
    filename: str,
    fn_name: str,
    unsafe_ok: bool,
):
    if isinstance(e, WildcardPattern):
        raise SemanticError(_diag(filename, e.line, e.col, "wildcard pattern `_` is only valid in match arms"))
    if isinstance(e, BoolLit):
        return _typed(e, "Bool")
    if isinstance(e, NilLit):
        return _typed(e, NONE_LIT_TYPE)
    if isinstance(e, Literal):
        if isinstance(e.value, bool):
            return _typed(e, "Bool")
        if isinstance(e.value, int):
            return _typed(e, "Int")
        if isinstance(e.value, float):
            return _typed(e, "Float")
        return _typed(e, "String")
    if isinstance(e, Name):
        local = _lookup(e.value, scopes)
        if local is not None:
            move.check_use(e.value, filename, e.line, e.col)
            borrow.check_read(e.value, filename, e.line, e.col)
            if owned is not None:
                owned.check_use(e.value, Span.at(filename, e.line, e.col))
            return _typed(e, local)
        if e.value in fn_groups:
            if len(fn_groups[e.value]) > 1:
                raise SemanticError(_diag(filename, e.line, e.col, f"ambiguous function reference {e.value}; call it with typed args"))
            decl = fn_groups[e.value][0]
            return _typed(e, _fn_type(decl.params, decl.ret, unsafe=getattr(decl, "unsafe", False)))
        if e.value in structs or e.value in enums:
            return _typed(e, "Any")
        sig = BUILTIN_SIGS.get(e.value)
        if sig is not None:
            _require_freestanding_builtin_allowed(e.value, filename, e.line, e.col)
            if sig.args is None:
                return _typed(e, "Any")
            return _typed(e, f"fn({', '.join(sig.args)}) -> {sig.ret}")
        raise SemanticError(_diag(filename, e.line, e.col, f"undefined name {e.value}"))
    if isinstance(e, SizeOfTypeExpr):
        try:
            layout_of_type(e.type_name, structs, mode="query")
        except LayoutError as err:
            raise SemanticError(_diag(filename, e.line, e.col, str(err))) from err
        setattr(e, "query_type", _canonical_type(e.type_name))
        return _typed(e, "Int")
    if isinstance(e, AlignOfTypeExpr):
        try:
            layout_of_type(e.type_name, structs, mode="query")
        except LayoutError as err:
            raise SemanticError(_diag(filename, e.line, e.col, str(err))) from err
        setattr(e, "query_type", _canonical_type(e.type_name))
        return _typed(e, "Int")
    if isinstance(e, BitSizeOfTypeExpr):
        try:
            lay = layout_of_type(e.type_name, structs, mode="query")
        except LayoutError as err:
            raise SemanticError(_diag(filename, e.line, e.col, str(err))) from err
        setattr(e, "query_type", _canonical_type(e.type_name))
        setattr(e, "query_bits", lay.bits)
        return _typed(e, "Int")
    if isinstance(e, MaxValTypeExpr):
        info = _int_info(e.type_name)
        if info is None:
            raise SemanticError(_diag(filename, e.line, e.col, f"maxVal expects an integer type, got {_canonical_type(e.type_name)}"))
        bits, signed = info
        setattr(e, "query_type", _canonical_type(e.type_name))
        setattr(e, "query_bits", bits)
        setattr(e, "query_signed", signed)
        return _typed(e, _canonical_type(e.type_name))
    if isinstance(e, MinValTypeExpr):
        info = _int_info(e.type_name)
        if info is None:
            raise SemanticError(_diag(filename, e.line, e.col, f"minVal expects an integer type, got {_canonical_type(e.type_name)}"))
        bits, signed = info
        setattr(e, "query_type", _canonical_type(e.type_name))
        setattr(e, "query_bits", bits)
        setattr(e, "query_signed", signed)
        return _typed(e, _canonical_type(e.type_name))
    if isinstance(e, (SizeOfValueExpr, AlignOfValueExpr)):
        # Query forms are type-only and must not consume moves/borrows from the source expression.
        owned_copy = owned.copy() if owned is not None else None
        borrow_copy = borrow.copy()
        move_copy = move.copy()
        val_ty = _infer(e.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned_copy, borrow_copy, move_copy, filename, fn_name, unsafe_ok)
        try:
            layout_of_type(val_ty, structs, mode="query")
        except LayoutError as err:
            raise SemanticError(_diag(filename, e.line, e.col, str(err))) from err
        setattr(e, "query_type", _canonical_type(val_ty))
        return _typed(e, "Int")
    if isinstance(e, AwaitExpr):
        return _typed(e, _infer(e.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok))
    if isinstance(e, Unary):
        if e.op in {"&", "&mut"}:
            if not isinstance(e.expr, Name):
                raise SemanticError(_diag(filename, e.line, e.col, "borrow expressions currently require a named binding"))
            owner = e.expr.value
            owner_ty = _lookup(owner, scopes)
            if owner_ty is None:
                raise SemanticError(_diag(filename, e.line, e.col, f"cannot borrow undefined name {owner}"))
            if owned is not None:
                owned.check_use(owner, Span.at(filename, e.line, e.col))
            fixed_owner = bool(_lookup_fixed(owner, fixed_scopes))
            borrow.ensure_can_borrow(owner, e.op == "&mut", fixed_owner, filename, e.line, e.col)
            if e.op == "&mut":
                return _typed(e, f"&mut {owner_ty}")
            return _typed(e, f"&{owner_ty}")
        inner = _infer(e.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        if e.op == "!":
            _require_type(filename, e.line, e.col, "Bool", inner, "unary !")
            return _typed(e, "Bool")
        if e.op == "-":
            if inner != "Any" and not _is_numeric_scalar_type(inner):
                raise SemanticError(_diag(filename, e.line, e.col, f"unary - expects number, got {inner}"))
            return _typed(e, inner)
        if e.op == "*":
            if not _is_ref_type(inner):
                raise SemanticError(_diag(filename, e.line, e.col, f"cannot dereference non-reference type {inner}"))
            return _typed(e, _strip_ref(inner))
        return _typed(e, inner)
    if isinstance(e, CastExpr):
        src = _infer(e.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        dst = _canonical_type(e.type_name)
        _validate_decl_type(dst, filename, e.line, e.col)
        src_c = _canonical_type(src)
        needs_unsafe_cast = (
            (src_c == "Any" and (_is_ref_type(dst) or dst.startswith("fn(") or dst.startswith("unsafe fn(")))
            or (dst == "Any" and (_is_ref_type(src_c) or src_c.startswith("fn(") or src_c.startswith("unsafe fn(")))
        )
        if needs_unsafe_cast and not unsafe_ok:
            raise SemanticError(_diag(filename, e.line, e.col, "this cast requires unsafe context"))
        if not _cast_supported(src, dst):
            raise SemanticError(_diag(filename, e.line, e.col, f"unsupported cast from {src} to {e.type_name}"))
        return _typed(e, dst)
    if isinstance(e, TypeAnnotated):
        src = _infer(e.expr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        dst = _canonical_type(e.type_name)
        _validate_decl_type(dst, filename, e.line, e.col)
        _require_type(filename, e.line, e.col, dst, src, "type annotation")
        return _typed(e, dst)
    if isinstance(e, Binary):
        l = _infer(e.left, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        r = _infer(e.right, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        if e.op in {"+", "-", "*", "/", "%"}:
            if e.op == "+" and _is_text_type(l) and _is_text_type(r):
                return _typed(e, "String")
            if _is_int_type(l) and _is_int_type(r):
                _require_strict_int_operands(filename, e.line, e.col, e.op, l, r)
                return _typed(e, _canonical_type(l))
            if _is_float_type(l) and _is_float_type(r):
                return _typed(e, _canonical_type(l))
            if (_is_int_type(l) and _is_float_type(r)) or (_is_float_type(l) and _is_int_type(r)):
                raise SemanticError(_diag(filename, e.line, e.col, f"mixed int/float arithmetic requires explicit cast for operator {e.op}"))
            raise SemanticError(_diag(filename, e.line, e.col, f"numeric operator {e.op} expects numeric operands"))
        if e.op in {"&", "|", "^", "<<", ">>"}:
            _require_strict_int_operands(filename, e.line, e.col, e.op, l, r)
            if e.op in {"<<", ">>"}:
                _require_shift_rhs_static_safe(filename, e.op, l, e.right)
            return _typed(e, _canonical_type(l))
        if e.op in {"==", "!=", "<", "<=", ">", ">="}:
            if _is_int_type(l) and _is_int_type(r):
                _require_strict_int_operands(filename, e.line, e.col, e.op, l, r)
            elif (_is_int_type(l) and _is_float_type(r)) or (_is_float_type(l) and _is_int_type(r)):
                raise SemanticError(_diag(filename, e.line, e.col, f"mixed int/float comparison requires explicit cast for operator {e.op}"))
            return _typed(e, "Bool")
        if e.op in {"&&", "||"}:
            _require_type(filename, e.line, e.col, "Bool", l, f"{e.op} left operand")
            _require_type(filename, e.line, e.col, "Bool", r, f"{e.op} right operand")
            return _typed(e, "Bool")
        if e.op == "??":
            if l == NONE_LIT_TYPE:
                return _typed(e, r)
            if not _is_option_type(l):
                raise SemanticError(_diag(filename, e.line, e.col, "left operand of ?? must be Option<T>"))
            inner = _option_inner(l)
            _require_type(filename, e.line, e.col, inner, r, "?? right operand")
            return _typed(e, inner)
        return _typed(e, "Any")
    if isinstance(e, Call):
        return _typed(e, _infer_call(e, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok))
    if isinstance(e, IndexExpr):
        obj_ty = _infer(e.obj, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        idx_ty = _infer(e.index, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        _require_type(filename, e.line, e.col, "Int", idx_ty, "index")
        base_ty = _strip_ref(_canonical_type(obj_ty))
        if base_ty in {"String", "str"}:
            raise SemanticError(
                _diag(
                    filename,
                    e.line,
                    e.col,
                    "cannot index UTF-8 text directly; use bytes/chars APIs instead",
                )
            )
        if _is_slice_type(base_ty):
            return _typed(e, _slice_inner(base_ty))
        if _is_vec_type(base_ty):
            return _typed(e, _vec_inner(base_ty))
        return _typed(e, "Any")
    if isinstance(e, FieldExpr):
        obj_ty = _infer(e.obj, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)

        # Method-like access on slices/vecs is handled in call inference.

        # Handle struct field access (local or qualified/imported)
        base_obj_ty = _strip_ref(_canonical_type(obj_ty))
        struct_decl = None
        if base_obj_ty.startswith("struct:"):
            struct_name = base_obj_ty[7:]
            struct_decl = structs.get(struct_name)
            if struct_decl is None:
                raise SemanticError(_diag(filename, e.line, e.col, f"unknown struct {struct_name}"))
        elif base_obj_ty in structs:
            struct_decl = structs[base_obj_ty]
        else:
            for struct_name, decl in structs.items():
                if "::" in struct_name and struct_name.endswith(f"::{base_obj_ty}"):
                    struct_decl = decl
                    break

        if struct_decl is not None:
            for fname, fty in struct_decl.fields:
                if fname == e.field:
                    return _typed(e, fty)
            raise SemanticError(_diag(filename, e.line, e.col, f"struct {struct_decl.name} has no field {e.field}"))

        return _typed(e, "Any")
    if isinstance(e, ModuleAccessExpr):
        obj_ty = _infer(e.obj, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        
        # Handle qualified access to imported symbols (module::symbol)
        if isinstance(e.obj, Name):
            obj_type = _lookup(e.obj.value, scopes)
            if obj_type is not None and obj_type.startswith("module:"):
                # This is a qualified access to an imported module symbol
                qualified_name = f"{e.obj.value}::{e.module}"
                symbol_type = _lookup(qualified_name, scopes)
                if symbol_type is not None:
                    return _typed(e, symbol_type)
                else:
                    raise SemanticError(_diag(filename, e.line, e.col, f"module {e.obj.value} has no symbol {e.module}"))
        
        raise SemanticError(_diag(filename, e.line, e.col, f"invalid module access {e.obj.value}::{e.module}"))
        return _typed(e, "Any")
    if isinstance(e, ArrayLit):
        if not e.elements:
            return _typed(e, "[Any]")
        first_ty = _infer(e.elements[0], scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        for el in e.elements[1:]:
            ety = _infer(el, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
            _require_type(filename, el.line, el.col, first_ty, ety, "array element")
        return _typed(e, f"[{first_ty}]")
    if isinstance(e, StructLit):
        decl = structs.get(e.name)
        if decl is None:
            raise SemanticError(_diag(filename, e.line, e.col, f"undefined struct {e.name}"))
        field_map: dict[str, Any] = {}
        for fname, fexpr in e.fields:
            if fname in field_map:
                raise SemanticError(_diag(filename, e.line, e.col, f"duplicate field {fname} in {e.name} literal"))
            field_map[fname] = fexpr
        declared_fields = {fname for fname, _ in decl.fields}
        for fname in field_map:
            if fname not in declared_fields:
                raise SemanticError(_diag(filename, e.line, e.col, f"unknown field {fname} for struct {e.name}"))
        for fname, fty in decl.fields:
            fexpr = field_map.get(fname)
            if fexpr is None:
                raise SemanticError(_diag(filename, e.line, e.col, f"missing field {fname} for struct {e.name}"))
            ety = _infer(fexpr, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
            _require_type(filename, getattr(fexpr, "line", e.line), getattr(fexpr, "col", e.col), fty, ety, f"field {fname} of {e.name}")
        return _typed(e, e.name)
    return _typed(e, "Any")


def _check_call_arg_borrows(
    args: list[Any],
    fixed_scopes: list[dict[str, bool]],
    borrow: _BorrowState,
    filename: str,
):
    temp = borrow.copy()
    for arg in args:
        if not (isinstance(arg, Unary) and arg.op in {"&", "&mut"} and isinstance(arg.expr, Name)):
            continue
        owner = arg.expr.value
        fixed_owner = bool(_lookup_fixed(owner, fixed_scopes))
        mutable = arg.op == "&mut"
        temp.ensure_can_borrow(owner, mutable, fixed_owner, filename, arg.line, arg.col)
        if mutable:
            temp.mutable_borrowed.add(owner)
        else:
            temp.shared_counts[owner] = temp.shared_counts.get(owner, 0) + 1


def _infer_call(
    e: Call,
    scopes: list[dict[str, str]],
    fixed_scopes: list[dict[str, bool]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    owned: _OwnedState | None,
    borrow: _BorrowState,
    move: _MoveState,
    filename: str,
    fn_name: str,
    unsafe_ok: bool,
) -> str:
    spawn_like = False
    if isinstance(e.fn, Name):
        base = e.fn.value[2:] if e.fn.value.startswith("__") else e.fn.value
        spawn_like = base == "spawn"
    arg_types: list[str] = []
    for i, arg in enumerate(e.args):
        if spawn_like and i == 0 and isinstance(arg, Name) and arg.value in fn_groups and len(fn_groups[arg.value]) > 1:
            arg_types.append("Any")
            continue
        arg_types.append(_infer(arg, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok))
    _check_call_arg_borrows(e.args, fixed_scopes, borrow, filename)

    def _require_unsafe_context(callee_name: str, line: int, col: int) -> None:
        if unsafe_ok:
            return
        raise SemanticError(_diag(filename, line, col, f"call to unsafe function {callee_name} requires unsafe context"))

    if isinstance(e.fn, Name):
        name = e.fn.value
        builtin_base = name[2:] if name.startswith("__") else name
        if builtin_base == "spawn":
            if len(e.args) < 1:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects at least a function argument"))
            worker = e.args[0]
            worker_param_tys: list[str]
            worker_ret_ty: str
            worker_unsafe = False
            if isinstance(worker, Name) and worker.value in fn_groups:
                known_types = set(PRIMITIVES) | set(structs.keys()) | set(enums.keys())
                worker_decl = _choose_impl(worker.value, fn_groups[worker.value], arg_types[1:], known_types, filename, e.line, e.col)
                worker_param_tys = [pty for _, pty in worker_decl.params]
                worker_ret_ty = worker_decl.ret
                worker_unsafe = bool(getattr(worker_decl, "unsafe", False))
                setattr(worker, "inferred_type", _fn_type(worker_decl.params, worker_decl.ret, unsafe=worker_unsafe))
                if isinstance(worker_decl, FnDecl):
                    setattr(e, "spawn_resolved_name", worker_decl.symbol or worker_decl.name)
            else:
                worker_ty = arg_types[0]
                parsed = _parse_fn_type(worker_ty)
                if parsed is None:
                    raise SemanticError(_diag(filename, worker.line, worker.col, f"{name} expects function value as arg 0"))
                worker_param_tys, worker_ret_ty, worker_unsafe = parsed
            if worker_unsafe:
                _require_unsafe_context(
                    worker.value if isinstance(worker, Name) else "<unsafe fn>",
                    worker.line,
                    worker.col,
                )
            if len(worker_param_tys) != len(e.args) - 1:
                raise SemanticError(
                    _diag(
                        filename,
                        e.line,
                        e.col,
                        f"{name} worker expects {len(worker_param_tys)} args, got {len(e.args) - 1}",
                    )
                )
            for i, (expected, arg) in enumerate(zip(worker_param_tys, e.args[1:]), start=1):
                aty = arg_types[i]
                _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for {name}")
                if not _is_ref_type(expected) and expected != "Any":
                    _consume_if_move_name(arg, aty, move, filename, arg.line, arg.col)
                _require_send(aty, structs, filename, arg.line, arg.col, f"spawn arg {i}")
                if _is_ref_type(aty):
                    _require_sync(_strip_ref(aty), structs, filename, arg.line, arg.col, f"spawn arg {i}")
            _require_send(worker_ret_ty, structs, filename, e.line, e.col, "spawn worker return")
            return "Int"
        if builtin_base in {"countOnes", "leadingZeros", "trailingZeros", "popcnt", "clz", "ctz"}:
            if len(e.args) != 1:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 1 args, got {len(e.args)}"))
            aty = arg_types[0]
            if not _is_int_type(aty):
                raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"{name} expects an integer argument, got {aty}"))
            return "Int"
        if builtin_base in {"rotl", "rotr"}:
            if len(e.args) != 2:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 2 args, got {len(e.args)}"))
            vty = arg_types[0]
            sty = arg_types[1]
            if not _is_int_type(vty):
                raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"{name} expects integer arg 0, got {vty}"))
            if not _is_int_type(sty):
                raise SemanticError(_diag(filename, e.args[1].line, e.args[1].col, f"{name} expects integer arg 1, got {sty}"))
            return _canonical_type(vty)
        if builtin_base == "vec_new":
            if len(e.args) != 0:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 0 args, got {len(e.args)}"))
            return "Any"
        if builtin_base == "vec_from":
            if len(e.args) != 1:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 1 args, got {len(e.args)}"))
            src_ty = _canonical_type(arg_types[0])
            if _is_vec_type(src_ty):
                return src_ty
            if _is_slice_type(src_ty):
                return f"Vec<{_slice_inner(src_ty)}>"
            raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"{name} expects [T] or Vec<T>, got {src_ty}"))
        if builtin_base == "vec_len":
            if len(e.args) != 1:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 1 args, got {len(e.args)}"))
            src_ty = _canonical_type(arg_types[0])
            if not _is_vec_type(src_ty):
                raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"{name} expects Vec<T>, got {src_ty}"))
            return "Int"
        if builtin_base == "vec_get":
            if len(e.args) != 2:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 2 args, got {len(e.args)}"))
            src_ty = _canonical_type(arg_types[0])
            if not _is_vec_type(src_ty):
                raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"{name} expects Vec<T>, got {src_ty}"))
            _require_type(filename, e.args[1].line, e.args[1].col, "Int", arg_types[1], f"arg 1 for {name}")
            return f"Option<{_vec_inner(src_ty)}>"
        if builtin_base == "vec_set":
            if len(e.args) != 3:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 3 args, got {len(e.args)}"))
            src_ty = _canonical_type(arg_types[0])
            if not _is_vec_type(src_ty):
                raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"{name} expects Vec<T>, got {src_ty}"))
            _require_type(filename, e.args[1].line, e.args[1].col, "Int", arg_types[1], f"arg 1 for {name}")
            _require_type(filename, e.args[2].line, e.args[2].col, _vec_inner(src_ty), arg_types[2], f"arg 2 for {name}")
            return "Int"
        if builtin_base == "vec_push":
            if len(e.args) != 2:
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 2 args, got {len(e.args)}"))
            src_ty = _canonical_type(arg_types[0])
            if not _is_vec_type(src_ty):
                raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"{name} expects Vec<T>, got {src_ty}"))
            _require_type(filename, e.args[1].line, e.args[1].col, _vec_inner(src_ty), arg_types[1], f"arg 1 for {name}")
            return "Int"
        if name in fn_groups:
            known_types = set(PRIMITIVES) | set(structs.keys()) | set(enums.keys())
            decl = _choose_impl(name, fn_groups[name], arg_types, known_types, filename, e.line, e.col)
            if getattr(decl, "unsafe", False):
                _require_unsafe_context(name, e.line, e.col)
            if len(e.args) != len(decl.params):
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects {len(decl.params)} args, got {len(e.args)}"))
            for i, ((_, pty), arg) in enumerate(zip(decl.params, e.args)):
                aty = arg_types[i]
                if not _is_typevar(pty, known_types):
                    _require_type(filename, arg.line, arg.col, pty, aty, f"arg {i} for {name}")
                if not _is_ref_type(pty) and pty != "Any" and not _is_typevar(pty, known_types):
                    _consume_if_move_name(arg, aty, move, filename, arg.line, arg.col)
            if isinstance(decl, FnDecl):
                e.resolved_name = decl.symbol or decl.name
            return decl.ret
        local = _lookup(name, scopes)
        if local is not None:
            setattr(e.fn, "inferred_type", local)
            parsed = _parse_fn_type(local)
            if parsed is None:
                raise SemanticError(_diag(filename, e.line, e.col, f"cannot call non-function value {name} of type {local}"))
            param_tys, ret_ty, callee_unsafe = parsed
            if callee_unsafe:
                _require_unsafe_context(name, e.line, e.col)
            if len(param_tys) != len(e.args):
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects {len(param_tys)} args, got {len(e.args)}"))
            for i, (expected, arg) in enumerate(zip(param_tys, e.args)):
                aty = arg_types[i]
                _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for {name}")
                if not _is_ref_type(expected) and expected != "Any":
                    _consume_if_move_name(arg, aty, move, filename, arg.line, arg.col)
            return ret_ty
        if name in structs:
            fields = structs[name].fields
            if len(e.args) != len(fields):
                raise SemanticError(_diag(filename, e.line, e.col, f"struct {name} expects {len(fields)} fields, got {len(e.args)}"))
            for i, ((_, fty), arg) in enumerate(zip(fields, e.args)):
                aty = arg_types[i]
                _require_type(filename, arg.line, arg.col, fty, aty, f"struct field for {name}")
                _consume_if_move_name(arg, aty, move, filename, arg.line, arg.col)
            return name
        sig = BUILTIN_SIGS.get(name)
        if sig is not None:
            _require_freestanding_builtin_allowed(name, filename, e.line, e.col)
            if sig.args is not None and len(e.args) != len(sig.args):
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects {len(sig.args)} args, got {len(e.args)}"))
            if sig.args is not None:
                for i, (expected, arg) in enumerate(zip(sig.args, e.args)):
                    aty = arg_types[i]
                    _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for {name}")
            return sig.ret
        raise SemanticError(_diag(filename, e.line, e.col, f"undefined function {name}"))
    if isinstance(e.fn, FieldExpr):
        obj_ty = _infer(e.fn.obj, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)

        # Slice/Vec method sugar: <container>.get(index) -> Option<elem>
        if e.fn.field == "get":
            if len(e.args) != 1:
                raise SemanticError(_diag(filename, e.line, e.col, "get expects 1 argument"))
            idx_ty = arg_types[0] if arg_types else "Any"
            _require_type(filename, e.args[0].line, e.args[0].col, "Int", idx_ty, "arg 0 for get")
            base_ty = _strip_ref(_canonical_type(obj_ty))
            if _is_slice_type(base_ty):
                return f"Option<{_slice_inner(base_ty)}>"
            if _is_vec_type(base_ty):
                return f"Option<{_vec_inner(base_ty)}>"
            raise SemanticError(_diag(filename, e.fn.line, e.fn.col, f"get is only supported on [T]/Vec<T>, got {obj_ty}"))
        
        # Handle struct field callables
        base_obj_ty = _strip_ref(_canonical_type(obj_ty))
        struct_decl = None
        if base_obj_ty.startswith("struct:"):
            struct_decl = structs.get(base_obj_ty[7:])
        elif base_obj_ty in structs:
            struct_decl = structs[base_obj_ty]
        else:
            for struct_name, decl in structs.items():
                if "::" in struct_name and struct_name.endswith(f"::{base_obj_ty}"):
                    struct_decl = decl
                    break

        if struct_decl is not None:
            field_ty = None
            for fname, fty in struct_decl.fields:
                if fname == e.fn.field:
                    field_ty = fty
                    break
            if field_ty is None:
                raise SemanticError(_diag(filename, e.line, e.col, f"struct {struct_decl.name} has no field {e.fn.field}"))
            if not field_ty.startswith("fn("):
                raise SemanticError(_diag(filename, e.line, e.col, f"field {e.fn.field} is not callable"))
            parsed = _parse_fn_type(field_ty)
            param_tys, ret_ty, callee_unsafe = parsed
            if callee_unsafe:
                _require_unsafe_context(f"{struct_decl.name}.{e.fn.field}", e.line, e.col)
            if len(param_tys) != len(e.args):
                raise SemanticError(_diag(filename, e.line, e.col, f"{struct_decl.name}.{e.fn.field} expects {len(param_tys)} args, got {len(e.args)}"))
            for i, (expected, arg) in enumerate(zip(param_tys, e.args)):
                aty = arg_types[i]
                _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for {struct_decl.name}.{e.fn.field}")
                if not _is_ref_type(expected) and expected != "Any":
                    _consume_if_move_name(arg, aty, move, filename, arg.line, arg.col)
            return ret_ty
        
        return _typed(e, "Any")
    if isinstance(e.fn, ModuleAccessExpr):
        obj_ty = _infer(e.fn.obj, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
        
        # Handle qualified access to imported symbols (module::symbol)
        if isinstance(e.fn.obj, Name):
            obj_type = _lookup(e.fn.obj.value, scopes)
            if obj_type is not None and obj_type.startswith("module:"):
                # This is a qualified access to an imported module symbol
                qualified_name = f"{e.fn.obj.value}::{e.fn.module}"
                symbol_type = _lookup(qualified_name, scopes)
                if symbol_type is not None:
                    # Check if it's a function
                    if symbol_type.startswith("fn("):
                        parsed = _parse_fn_type(symbol_type)
                        param_tys, ret_ty, callee_unsafe = parsed
                        if callee_unsafe:
                            _require_unsafe_context(f"{e.fn.obj.value}::{e.fn.module}", e.line, e.col)
                        if len(param_tys) != len(e.args):
                            raise SemanticError(_diag(filename, e.line, e.col, f"{e.fn.obj.value}::{e.fn.module} expects {len(param_tys)} args, got {len(e.args)}"))
                        for i, (expected, arg) in enumerate(zip(param_tys, e.args)):
                            aty = arg_types[i]
                            _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for {e.fn.obj.value}::{e.fn.module}")
                            if not _is_ref_type(expected) and expected != "Any":
                                _consume_if_move_name(arg, aty, move, filename, arg.line, arg.col)
                        return ret_ty
                    else:
                        raise SemanticError(_diag(filename, e.line, e.col, f"{e.fn.obj.value}::{e.fn.module} is not callable"))
                else:
                    raise SemanticError(_diag(filename, e.line, e.col, f"module {e.fn.obj.value} has no symbol {e.fn.module}"))
        
        raise SemanticError(_diag(filename, e.line, e.col, f"invalid module access {e.fn.obj.value}::{e.fn.module}"))
        return "Any"
    callee_ty = _infer(e.fn, scopes, fixed_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok)
    setattr(e.fn, "inferred_type", callee_ty)
    parsed = _parse_fn_type(callee_ty)
    if parsed is None:
        raise SemanticError(_diag(filename, e.line, e.col, f"cannot call value of non-function type {callee_ty}"))
    param_tys, ret_ty, callee_unsafe = parsed
    if callee_unsafe:
        _require_unsafe_context("<unsafe fn>", e.line, e.col)
    if len(param_tys) != len(e.args):
        raise SemanticError(_diag(filename, e.line, e.col, f"callee expects {len(param_tys)} args, got {len(e.args)}"))
    for i, (expected, arg) in enumerate(zip(param_tys, e.args)):
        aty = arg_types[i]
        _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for function pointer call")
        if not _is_ref_type(expected) and expected != "Any":
            _consume_if_move_name(arg, aty, move, filename, arg.line, arg.col)
    return ret_ty


def _is_alloc_call(expr):
    return isinstance(expr, Call) and isinstance(expr.fn, Name) and expr.fn.value == "alloc"


def _is_free_call(expr):
    return isinstance(expr, Call) and isinstance(expr.fn, Name) and expr.fn.value == "free" and len(expr.args) == 1
