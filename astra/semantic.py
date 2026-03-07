"""Semantic analysis, typing, and safety checks for Astra programs."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from pathlib import Path
from itertools import product

from astra.ast import *
from astra.int_types import is_int_type_name, parse_int_type_name
from astra.layout import LayoutError, canonical_type as _layout_canonical_type, layout_of_type
from astra.module_resolver import resolve_import_path
from astra.parser import parse


class SemanticError(Exception):
    """Error type raised by the semantic subsystem.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pass


def _diag(filename: str, line: int, col: int, msg: str) -> str:
    return f"SEM {filename}:{line}:{col}: {msg}"


FLOAT_TYPES = {"f32", "f64"}
PRIMITIVES = {"Int", "isize", "usize", "Float", "f32", "f64", "String", "str", "Bool", "Any", "Void", "Never", "Bytes"}
COPY_SCALAR_TYPES = {"Float", "f32", "f64", "Bool"}
NONE_LIT_TYPE = "<none>"
_TRAIT_IMPLS_STACK: list[dict[str, set[str]]] = [{}]
_KNOWN_TRAITS_STACK: list[set[str]] = [set()]
_TRAITS_STACK: list[dict[str, TraitDecl]] = [{}]
_FN_GROUPS_STACK: list[dict[str, list[FnDecl | ExternFnDecl]]] = [{}]



def _parse_parametric_type(typ: Any) -> tuple[str, list[str]] | None:
    t = type_text(typ).strip()
    if "<" not in t or not t.endswith(">"):
        return None
    lt = t.find("<")
    base = t[:lt].strip()
    inner = t[lt + 1 : -1].strip()
    if not base or not inner:
        return None
    args = _split_top_level(inner, ",")
    if not args:
        return None
    return base, args



def _union_members(typ: Any) -> list[str]:
    t = type_text(typ).strip()
    if "|" not in t:
        return [t]
    return [p.strip() for p in _split_top_level(t, "|") if p.strip()]


def _is_union_type(typ: Any) -> bool:
    return len(_union_members(typ)) > 1


def _normalize_union(types: list[str]) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for t in types:
        for m in _union_members(t):
            c = _canonical_type(m)
            if c in seen:
                continue
            seen.add(c)
            out.append(c)
    return " | ".join(out)


def _is_nullable_union(typ: Any) -> bool:
    members = _union_members(_canonical_type(typ))
    return "none" in members and len(members) >= 2


def _remove_none_from_union(typ: Any) -> str:
    members = [m for m in _union_members(_canonical_type(typ)) if m != "none"]
    if not members:
        return "none"
    if len(members) == 1:
        return members[0]
    return _normalize_union(members)


def _remove_member_from_union(typ: Any, member: str) -> str:
    m = _canonical_type(member)
    members = [v for v in _union_members(_canonical_type(typ)) if _canonical_type(v) != m]
    if not members:
        return _canonical_type(typ)
    if len(members) == 1:
        return members[0]
    return _normalize_union(members)


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


def _gpu_type_arg(typ: Any, base: str) -> str | None:
    parsed = _parse_parametric_type(typ)
    if parsed is None:
        return None
    head, args = parsed
    if head != base or len(args) != 1:
        return None
    return args[0]


def _is_gpu_buffer_type(typ: Any) -> bool:
    return _gpu_type_arg(typ, "GpuBuffer") is not None


def _is_gpu_slice_type(typ: Any) -> bool:
    return _gpu_type_arg(typ, "GpuSlice") is not None


def _is_gpu_mut_slice_type(typ: Any) -> bool:
    return _gpu_type_arg(typ, "GpuMutSlice") is not None


def _is_gpu_view_type(typ: Any) -> bool:
    return _is_gpu_slice_type(typ) or _is_gpu_mut_slice_type(typ)


def _is_gpu_memory_type(typ: Any) -> bool:
    return _is_gpu_buffer_type(typ) or _is_gpu_view_type(typ)


def _gpu_element_type(typ: Any) -> str | None:
    for base in ("GpuBuffer", "GpuSlice", "GpuMutSlice"):
        inner = _gpu_type_arg(typ, base)
        if inner is not None:
            return inner
    return None


def _strip_ref(typ: Any) -> str:
    t = _canonical_type(typ)
    if t.startswith("&mut "):
        return t[5:]
    if t.startswith("&"):
        return t[1:]
    return t


def _is_ref_type(typ: Any) -> bool:
    canonical = _canonical_type(typ)
    return canonical.startswith("&") or canonical.startswith("*")


def _is_mut_ref_type(typ: Any) -> bool:
    return _canonical_type(typ).startswith("&mut ")


def _canonical_type(typ: Any) -> str:
    t = type_text(typ)
    # Handle nullable syntax T? 
    if t.endswith("?"):
        base = t[:-1].strip()
        return _normalize_union([_canonical_type(base), "none"])
    if "|" in t:
        return _normalize_union(_split_top_level(t, "|"))
    if t == "Bytes":
        return "Vec<u8>"
    if t.startswith("&mut "):
        return f"&mut {_canonical_type(t[5:])}"
    if t.startswith("&"):
        return f"&{_canonical_type(t[1:])}"
    if _is_slice_type(t):
        return f"[{_canonical_type(_slice_inner(t))}]"
    if _is_vec_type(t):
        return f"Vec<{_canonical_type(_vec_inner(t))}>"
    parsed = _parse_parametric_type(t)
    if parsed is not None:
        base, args = parsed
        return f"{base}<{', '.join(_canonical_type(a) for a in args)}>"
    return t


def _substitute_typevars(typ: Any, bindings: dict[str, str]) -> str:
    t = type_text(typ).strip()
    if "|" in t:
        return _normalize_union([_substitute_typevars(p, bindings) for p in _split_top_level(t, "|")])
    if t in bindings:
        return _canonical_type(bindings[t])
    if t.startswith("&mut "):
        return f"&mut {_substitute_typevars(t[5:], bindings)}"
    if t.startswith("&"):
        return f"&{_substitute_typevars(t[1:], bindings)}"
    if _is_slice_type(t):
        return f"[{_substitute_typevars(_slice_inner(t), bindings)}]"
    parsed = _parse_parametric_type(t)
    if parsed is not None:
        base, args = parsed
        return f"{base}<{', '.join(_substitute_typevars(a, bindings) for a in args)}>"
    return _canonical_type(t)


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
    if _is_gpu_memory_type(c):
        return True
    return _is_ref_type(c) and not _is_mut_ref_type(c)


def _is_gpu_scalar_type(typ: str) -> bool:
    c = _canonical_type(typ)
    return c in {"Bool", "Int", "isize", "usize", "Float", "f32", "f64"} or _is_int_type(c)


def _is_gpu_safe_type(typ: str, structs: dict[str, StructDecl], *, seen: set[str] | None = None) -> bool:
    c = _canonical_type(typ)
    if c in {"Void", "Never"}:
        return True
    if _is_gpu_scalar_type(c):
        return True
    if _is_gpu_memory_type(c):
        inner = _gpu_element_type(c)
        return inner is not None and _is_gpu_safe_type(inner, structs, seen=seen)
    if c in {"String", "str", "Any"}:
        return False
    if _is_vec_type(c) or _is_slice_type(c):
        return False
    if c.startswith("fn(") or c.startswith("unsafe fn("):
        return False
    if c.startswith("&"):
        return False
    if c in structs:
        guard = seen or set()
        if c in guard:
            return True
        guard.add(c)
        for _, fty in structs[c].fields:
            if not _is_gpu_safe_type(fty, structs, seen=guard):
                return False
        guard.remove(c)
        return True
    return False


def _is_gpu_kernel_param_type(typ: str, structs: dict[str, StructDecl]) -> bool:
    c = _canonical_type(typ)
    if _is_gpu_view_type(c):
        inner = _gpu_element_type(c)
        return inner is not None and _is_gpu_safe_type(inner, structs)
    if _is_gpu_scalar_type(c):
        return True
    if c in structs:
        return _is_gpu_safe_type(c, structs)
    return False


def _gpu_launch_arg_compatible(expected: str, actual: str) -> bool:
    exp = _canonical_type(expected)
    act = _canonical_type(actual)
    if _same_type(exp, act):
        return True
    exp_el = _gpu_element_type(exp)
    act_el = _gpu_element_type(act)
    if exp_el is None or act_el is None:
        return False
    if _is_gpu_slice_type(exp) and (_is_gpu_buffer_type(act) or _is_gpu_slice_type(act) or _is_gpu_mut_slice_type(act)):
        return _same_type(exp_el, act_el)
    if _is_gpu_mut_slice_type(exp) and (_is_gpu_buffer_type(act) or _is_gpu_mut_slice_type(act)):
        return _same_type(exp_el, act_el)
    if _is_gpu_buffer_type(exp) and _is_gpu_buffer_type(act):
        return _same_type(exp_el, act_el)
    return False


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
    """Data container used by semantic.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    args: list[str] | None
    ret: str


@dataclass(frozen=True)
class Span:
    """Source span metadata used for diagnostics and editor features.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    filename: str
    line: int
    col: int

    @classmethod
    def at(cls, filename: str, line: int, col: int) -> "Span":
        """Execute the `at` routine.
        
        Parameters:
            filename: Filename context used for diagnostics or path resolution.
            line: Input value used by this routine.
            col: Input value used by this routine.
        
        Returns:
            Value described by the function return annotation.
        """
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
    "__atomic_int_new": BuiltinSig(["Int"], "Int"),
    "__atomic_load": BuiltinSig(["Int"], "Int"),
    "__atomic_store": BuiltinSig(["Int", "Int"], "Int"),
    "__atomic_fetch_add": BuiltinSig(["Int", "Int"], "Int"),
    "__atomic_compare_exchange": BuiltinSig(["Int", "Int", "Int"], "Bool"),
    "mutex_new": BuiltinSig([], "Int"),
    "mutex_lock": BuiltinSig(["Int", "Int"], "Int"),
    "mutex_unlock": BuiltinSig(["Int", "Int"], "Int"),
    "chan_new": BuiltinSig([], "Int"),
    "chan_send": BuiltinSig(["Int", "Any"], "Int"),
    "chan_recv_try": BuiltinSig(["Int"], "Any?"),
    "chan_recv_blocking": BuiltinSig(["Int"], "Any"),
    "chan_close": BuiltinSig(["Int"], "Int"),
    "alloc": BuiltinSig(["Int"], "Int"),
    "free": BuiltinSig(["Int"], "Void"),
    "await_result": BuiltinSig(["Any"], "Any"),
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
    "rand_bytes": BuiltinSig(["Int"], "Any"),
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
    "vec_get": BuiltinSig(["Any", "Int"], "Any | none"),
    "vec_set": BuiltinSig(["Any", "Int", "Any"], "Int"),
    "vec_push": BuiltinSig(["Any", "Any"], "Int"),
}

for _name, _sig in list(BUILTIN_SIGS.items()):
    if _name.startswith("__"):
        continue
    if _name in {"print", "len", "read_file", "write_file", "args", "arg", "spawn", "join", "alloc", "free", "await_result"}:
        continue
    BUILTIN_SIGS[f"__{_name}"] = _sig


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
    "rand_bytes",
    "mutex_new",
    "mutex_lock",
    "mutex_unlock",
    "chan_new",
    "chan_send",
    "chan_recv_try",
    "chan_recv_blocking",
    "chan_close",
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

GPU_KERNEL_BUILTINS: set[str] = {
    "global_id",
    "thread_id",
    "block_id",
    "block_dim",
    "grid_dim",
    "barrier",
}
GPU_HOST_APIS: set[str] = {
    "available",
    "device_count",
    "device_name",
    "alloc",
    "copy",
    "read",
    "launch",
}
GPU_ALLOWED_IN_KERNEL_BUILTINS: set[str] = {
    "countOnes",
    "leadingZeros",
    "trailingZeros",
    "popcnt",
    "clz",
    "ctz",
    "rotl",
    "rotr",
    "vec_new",
    "vec_from",
    "vec_len",
    "vec_get",
    "vec_set",
    "vec_push",
}


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
        owner_mutable: bool,
        filename: str,
        line: int,
        col: int,
        origin: str | None = None,
    ):
        self.release_ref(ref_name)
        self.ensure_can_borrow(owner, mutable, owner_mutable, filename, line, col)
        if mutable:
            self.mutable_borrowed.add(owner)
        else:
            self.shared_counts[owner] = self.shared_counts.get(owner, 0) + 1
        self.ref_bindings[ref_name] = _BorrowInfo(owner, mutable)
        if origin is not None:
            self.ref_origins[ref_name] = origin

    def ensure_can_borrow(self, owner: str, mutable: bool, owner_mutable: bool, filename: str, line: int, col: int):
        has_shared = self.shared_counts.get(owner, 0) > 0
        has_mut = owner in self.mutable_borrowed
        if mutable:
            if not owner_mutable:
                raise SemanticError(_diag(filename, line, col, f"cannot mutably borrow immutable binding {owner}"))
            if has_mut or has_shared:
                details: list[str] = []
                if has_mut:
                    details.append("an active mutable borrow exists")
                if has_shared:
                    details.append(f"{self.shared_counts.get(owner, 0)} active shared borrow(s)")
                suffix = f" ({'; '.join(details)})" if details else ""
                raise SemanticError(_diag(filename, line, col, f"cannot mutably borrow {owner} while it is already borrowed{suffix}"))
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

    def ensure_can_move(self, name: str, filename: str, line: int, col: int):
        if self.shared_counts.get(name, 0) > 0:
            raise SemanticError(_diag(filename, line, col, f"cannot move {name} while it is immutably borrowed"))
        if name in self.mutable_borrowed:
            raise SemanticError(_diag(filename, line, col, f"cannot move {name} while it is mutably borrowed"))


class _MoveState:
    def __init__(self):
        self.moved: dict[str, bool] = {}
        self.fn_ret: str | None = None

    def copy(self):
        nxt = _MoveState()
        nxt.moved = self.moved.copy()
        nxt.fn_ret = self.fn_ret
        return nxt

    def merge(self, left: "_MoveState", right: "_MoveState"):
        merged: dict[str, bool] = {}
        for name in set(left.moved) | set(right.moved):
            merged[name] = left.moved.get(name, False) or right.moved.get(name, False)
        self.moved = merged
        self.fn_ret = left.fn_ret or right.fn_ret

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
    while isinstance(cur, (FieldExpr, IndexExpr)):
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
    if _is_union_type(expected):
        exp_members = _union_members(expected)
        if _is_union_type(actual):
            act_members = _union_members(actual)
            return all(any(_same_type(e, a) for e in exp_members) for a in act_members)
        return any(_same_type(e, actual) for e in exp_members)
    if _is_union_type(actual):
        return all(_same_type(expected, a) for a in _union_members(actual))
    if expected == actual:
        return True
    if expected.startswith("&") and not expected.startswith("&mut ") and actual.startswith("&mut "):
        return _same_type(expected[1:], actual[5:])
    exp_param = _parse_parametric_type(expected)
    act_param = _parse_parametric_type(actual)
    if exp_param is not None and act_param is not None:
        exp_base, exp_args = exp_param
        act_base, act_args = act_param
        if exp_base == act_base and len(exp_args) == len(act_args):
            if exp_base in {"GpuBuffer", "GpuSlice", "GpuMutSlice"}:
                return all(_same_type(ea, aa) or _canonical_type(aa) == "Any" for ea, aa in zip(exp_args, act_args))
            return all(_same_type(ea, aa) for ea, aa in zip(exp_args, act_args))
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
        if _is_nullable_union(expected):
            return
        raise SemanticError(_diag(filename, line, col, f"`none` requires nullable context for {what}, got {expected}"))
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
    if l == "Int" or r == "Int":
        return
    if l != r:
        raise SemanticError(_diag(filename, line, col, f"operator {op} requires matching integer types, got {left} and {right}"))


def _cast_supported(src: str, dst: str) -> bool:
    src_c = _canonical_type(src)
    dst_c = _canonical_type(dst)
    if _same_type(src_c, dst_c):
        return True
    # Support casting between equivalent nullable types
    if _is_nullable_union(src_c) and _is_nullable_union(dst_c):
        # Both are nullable, check if their non-nullable parts are compatible
        src_inner = _remove_none_from_union(src_c)
        dst_inner = _remove_none_from_union(dst_c)
        return _cast_supported(src_inner, dst_inner)
    # Support casting from nullable to non-nullable if inner types are compatible
    if _is_nullable_union(src_c) and not _is_nullable_union(dst_c):
        src_inner = _remove_none_from_union(src_c)
        return _cast_supported(src_inner, dst_c)
    # Support casting from non-nullable to nullable if inner types are compatible
    if not _is_nullable_union(src_c) and _is_nullable_union(dst_c):
        dst_inner = _remove_none_from_union(dst_c)
        return _cast_supported(src_c, dst_inner)
    def _is_generic_symbol_name(t: str) -> bool:
        return bool(re.fullmatch(r"[A-Z][A-Za-z0-9_]*", t)) and t not in PRIMITIVES
    if _is_numeric_scalar_type(src_c) and _is_numeric_scalar_type(dst_c):
        return True
    if src_c == "Bool" and (_is_numeric_scalar_type(dst_c) or dst_c == "Bool"):
        return True
    if dst_c == "Bool" and (_is_numeric_scalar_type(src_c) or src_c == "Bool"):
        return True
    if src_c == "Any":
        if _is_generic_symbol_name(dst_c):
            return True
        return _is_any_dynamic_cast_target(dst_c)
    if dst_c == "Any":
        if _is_generic_symbol_name(src_c):
            return True
        return _is_any_dynamic_cast_target(src_c) or _is_ref_type(src_c) or src_c.startswith("fn(")
    
    # Support pointer to integer conversions (ptrtoint)
    if _is_ref_type(src_c) and _is_int_type(dst_c):
        return True
    # Support integer to pointer conversions (inttoptr) 
    if _is_int_type(src_c) and _is_ref_type(dst_c):
        return True
    # Support pointer to pointer conversions (bitcast)
    if _is_ref_type(src_c) and _is_ref_type(dst_c):
        return True
    # Support none to pointer conversions (null pointer)
    if src_c == NONE_LIT_TYPE and _is_ref_type(dst_c):
        return True
    
    return False


def _is_any_dynamic_cast_target(typ: str) -> bool:
    c = _canonical_type(typ)
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(<.*>)?", c):
        return True
    return (
        c in {"Bool", "String", "str"}
        or _is_numeric_scalar_type(c)
        or _is_gpu_memory_type(c)
        or _is_ref_type(c)
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
    if v < 0:
        raise SemanticError(
            _diag(
                filename,
                getattr(rhs_expr, "line", 0),
                getattr(rhs_expr, "col", 0),
                f"negative shift count {v} in {op}; shift counts must be non-negative",
            )
        )
    if v >= bits:
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


def _consume_if_move_name(
    expr: Any,
    expr_ty: str,
    borrow: _BorrowState,
    move: _MoveState,
    filename: str,
    line: int,
    col: int,
):
    if isinstance(expr, Name) and not _is_copy_type(expr_ty):
        borrow.ensure_can_move(expr.value, filename, line, col)
        move.consume(expr.value, filename, line, col)


def _ref_return_tie_info(expr: Any, ref_param_names: set[str], borrow: _BorrowState) -> tuple[bool, str | None]:
    if isinstance(expr, Name):
        if expr.value in ref_param_names:
            return True, None
        origin = borrow.ref_origins.get(expr.value)
        if origin in ref_param_names:
            return True, None
        info = borrow.ref_bindings.get(expr.value)
        if info is not None and info.owner in ref_param_names:
            return True, None
        if info is not None:
            return False, f"returned `{expr.value}` currently borrows `{info.owner}`"
        if origin is not None:
            return False, f"returned `{expr.value}` originates from `{origin}`"
        return False, f"returned `{expr.value}` does not originate from an input reference parameter"
    return False, "only returning a named reference tied to an input reference parameter is currently supported"


def _ref_return_tied_to_param(expr: Any, ref_param_names: set[str], borrow: _BorrowState) -> bool:
    ok, _ = _ref_return_tie_info(expr, ref_param_names, borrow)
    return ok


def _lookup(name: str, scopes: list[dict[str, str]]) -> str | None:
    for scope in reversed(scopes):
        if name in scope:
            return scope[name]
    return None


def _scope_index(name: str, scopes: list[dict[str, str]]) -> int | None:
    for i in range(len(scopes) - 1, -1, -1):
        if name in scopes[i]:
            return i
    return None


def _ensure_ref_owner_outlives_binding(
    owner: str,
    ref_name: str,
    scopes: list[dict[str, str]],
    filename: str,
    line: int,
    col: int,
):
    owner_i = _scope_index(owner, scopes)
    ref_i = _scope_index(ref_name, scopes)
    if owner_i is None or ref_i is None:
        return
    if owner_i > ref_i:
        raise SemanticError(
            _diag(
                filename,
                line,
                col,
                (
                    f"reference {ref_name} cannot outlive borrowed value {owner} "
                    f"(owner scope depth {owner_i}, reference scope depth {ref_i})"
                ),
            )
        )


def _assign(name: str, typ: str, scopes: list[dict[str, str]], filename: str, line: int, col: int):
    for scope in reversed(scopes):
        if name in scope:
            scope[name] = typ
            return
    raise SemanticError(_diag(filename, line, col, f"assignment to undefined name {name}"))


def _lookup_mut(name: str, mut_scopes: list[dict[str, bool]]) -> bool | None:
    for scope in reversed(mut_scopes):
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
    if close + 1 > len(t) or t[close + 1] != " ":
        return None
    params_text = t[3:close].strip()
    ret = t[close + 1:].strip()
    if not ret:
        return None
    if not params_text:
        return [], ret, unsafe
    return _split_top_level(params_text, ","), ret, unsafe


def _fn_type(params: list[tuple[str, str]], ret: str, *, unsafe: bool = False) -> str:
    head = "unsafe fn" if unsafe else "fn"
    return f"{head}({', '.join(ty for _, ty in params)}) {ret}"


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
    if _is_gpu_memory_type(c):
        inner = _gpu_element_type(c)
        return inner is not None and _is_send_type(inner, structs, seen=seen)
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
    if _is_gpu_memory_type(c):
        inner = _gpu_element_type(c)
        return inner is not None and _is_sync_type(inner, structs, seen=seen)
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


def _current_trait_impls() -> dict[str, set[str]]:
    return _TRAIT_IMPLS_STACK[-1] if _TRAIT_IMPLS_STACK else {}


def _current_traits() -> dict[str, TraitDecl]:
    return _TRAITS_STACK[-1] if _TRAITS_STACK else {}


def _current_fn_groups() -> dict[str, list[FnDecl | ExternFnDecl]]:
    return _FN_GROUPS_STACK[-1] if _FN_GROUPS_STACK else {}


def _replace_self_type(typ: str, concrete: str) -> str:
    t = _canonical_type(typ)
    if t == "Self":
        return _canonical_type(concrete)
    if t.startswith("&mut "):
        inner = _replace_self_type(t[5:], concrete)
        return f"&mut {inner}"
    if t.startswith("&"):
        inner = _replace_self_type(t[1:], concrete)
        return f"&{inner}"
    if "<" in t and t.endswith(">"):
        parsed = _parse_parametric_type(t)
        if parsed is not None:
            base, args = parsed
            return f"{base}<{', '.join(_replace_self_type(a, concrete) for a in args)}>"
    return t


def _trait_satisfied_by_type(trait_name: str, concrete: str) -> bool:
    return len(_trait_missing_methods(trait_name, concrete)) == 0


def _trait_missing_methods_in_context(
    trait_name: str,
    concrete: str,
    *,
    traits: dict[str, TraitDecl],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    explicit_impls: dict[str, set[str]],
) -> list[str]:
    concrete_c = _canonical_type(concrete)
    if concrete_c in explicit_impls.get(trait_name, set()):
        return []
    decl = traits.get(trait_name)
    if decl is None:
        return [f"unknown trait {trait_name}"]
    missing: list[str] = []
    for mname, params, ret in decl.methods:
        target_params = [(n, _replace_self_type(t, concrete_c)) for n, t in params]
        target_ret = _replace_self_type(ret, concrete_c)
        cands = fn_groups.get(mname, [])
        matched = False
        for cand in cands:
            if len(cand.params) != len(target_params):
                continue
            if not all(
                _same_type(type_text(cp), type_text(tp))
                for (_, cp), (_, tp) in zip(cand.params, target_params)
            ):
                continue
            if not _same_type(type_text(cand.ret), target_ret):
                continue
            matched = True
            break
        if not matched:
            sig = f"{mname}({', '.join(type_text(t) for _, t in target_params)}) {target_ret}"
            missing.append(sig)
    return missing


def _trait_missing_methods(trait_name: str, concrete: str) -> list[str]:
    return _trait_missing_methods_in_context(
        trait_name,
        concrete,
        traits=_current_traits(),
        fn_groups=_current_fn_groups(),
        explicit_impls=_current_trait_impls(),
    )


def _where_bounds_satisfied_for_args(
    decl: FnDecl | ExternFnDecl,
    arg_types: list[str],
    known_types: set[str],
    *,
    traits: dict[str, TraitDecl],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    trait_impls: dict[str, set[str]],
) -> bool:
    matched = _match_decl_bindings(decl, arg_types, known_types)
    if matched is None:
        return False
    _, _, _, bindings = matched
    for tvar, trait_name in list(getattr(decl, "where_bounds", [])):
        concrete = bindings.get(tvar)
        if concrete is None:
            return False
        missing = _trait_missing_methods_in_context(
            trait_name,
            concrete,
            traits=traits,
            fn_groups=fn_groups,
            explicit_impls=trait_impls,
        )
        if missing:
            return False
    return True


def _match_decl_bindings(
    decl: FnDecl | ExternFnDecl,
    arg_types: list[str],
    known_types: set[str],
) -> tuple[int, int, int, dict[str, str]] | None:
    is_variadic = bool(getattr(decl, "is_variadic", False))
    if is_variadic:
        if len(arg_types) < len(decl.params):
            return None
    elif len(decl.params) != len(arg_types):
        return None
    type_vars = set(getattr(decl, "generics", []))
    for _, pty in decl.params:
        if _is_typevar(pty, known_types):
            type_vars.add(pty)
    bindings: dict[str, str] = {}
    exact = 0
    constrained = 0
    wildcards = 0
    for i, ((_, pty), aty) in enumerate(zip(decl.params, arg_types)):
        if i == 0 and _is_ref_type(pty):
            inner = _strip_ref(pty)
            if _is_typevar(inner, known_types):
                bound = bindings.get(inner)
                if bound is None:
                    bindings[inner] = aty
                elif not _same_type(bound, aty):
                    return None
                constrained += 1
                continue
            if _same_type(inner, aty):
                constrained += 1
                if _canonical_type(inner) == _canonical_type(aty):
                    exact += 1
                continue
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
    return (exact, constrained, wildcards, bindings)


def _decl_rejection_reason(
    decl: FnDecl | ExternFnDecl,
    arg_types: list[str],
    known_types: set[str],
) -> tuple[str, str]:
    is_variadic = bool(getattr(decl, "is_variadic", False))
    if is_variadic:
        if len(arg_types) < len(decl.params):
            return ("arity", f"expects at least {len(decl.params)} args, got {len(arg_types)}")
    elif len(decl.params) != len(arg_types):
        return ("arity", f"expects {len(decl.params)} args, got {len(arg_types)}")

    type_vars = set(getattr(decl, "generics", []))
    for _, pty in decl.params:
        if _is_typevar(pty, known_types):
            type_vars.add(pty)

    bindings: dict[str, str] = {}
    for i, ((_, pty), aty) in enumerate(zip(decl.params, arg_types), start=1):
        if i == 1 and _is_ref_type(pty):
            inner = _strip_ref(pty)
            if _is_typevar(inner, known_types):
                prev = bindings.get(inner)
                if prev is not None and not _same_type(prev, aty):
                    return ("generic", f"arg {i} gives inconsistent binding for {inner}: {prev} vs {aty}")
                bindings[inner] = aty
                continue
            if _same_type(inner, aty):
                continue
        if pty in type_vars:
            prev = bindings.get(pty)
            if prev is not None and not _same_type(prev, aty):
                return ("generic", f"arg {i} gives inconsistent binding for {pty}: {prev} vs {aty}")
            bindings[pty] = aty
            continue
        if pty == "Any":
            continue
        if not _same_type(pty, aty):
            return ("type", f"arg {i} expects {type_text(pty)}, got {aty}")

    for tvar, trait_name in list(getattr(decl, "where_bounds", [])):
        concrete = bindings.get(tvar)
        if concrete is None:
            return ("generic", f"could not bind type variable {tvar} for bound {tvar}: {trait_name}")
        missing = _trait_missing_methods(trait_name, concrete)
        if missing:
            return (
                "bound",
                f"{tvar}: {trait_name} not satisfied for {concrete}; missing {', '.join(missing)}",
            )
    return ("unknown", "not viable")


def _specialization_score(
    decl: FnDecl | ExternFnDecl,
    arg_types: list[str],
    known_types: set[str],
) -> tuple[int, int, int, int] | None:
    matched = _match_decl_bindings(decl, arg_types, known_types)
    if matched is None:
        return None
    exact, constrained, wildcards, bindings = matched
    where_bounds = list(getattr(decl, "where_bounds", []))
    if where_bounds:
        for tvar, trait_name in where_bounds:
            concrete = bindings.get(tvar)
            if concrete is None:
                return None
            if not _trait_satisfied_by_type(trait_name, concrete):
                return None
    return (exact, constrained, -wildcards, 0)


def _decl_signature_text(decl: FnDecl | ExternFnDecl) -> str:
    params = ", ".join(type_text(t) for _, t in decl.params)
    bounds = list(getattr(decl, "where_bounds", []))
    generics = list(getattr(decl, "generics", []))
    if not generics and bounds:
        seen_tvars: set[str] = set()
        for tv, _ in bounds:
            if tv not in seen_tvars:
                generics.append(tv)
                seen_tvars.add(tv)
    if bounds and generics:
        grouped: dict[str, list[str]] = {}
        for tv, tr in bounds:
            grouped.setdefault(tv, []).append(tr)
        gtext: list[str] = []
        for g in generics:
            cons = grouped.get(g, [])
            if cons:
                gtext.append(f"{g} {' + '.join(cons)}")
            else:
                gtext.append(g)
        return f"{decl.name}<{', '.join(gtext)}>({params}) {type_text(decl.ret)}"
    if generics:
        return f"{decl.name}<{', '.join(generics)}>({params}) {type_text(decl.ret)}"
    return f"{decl.name}({params}) {type_text(decl.ret)}"


def _decl_more_specific(a: FnDecl | ExternFnDecl, b: FnDecl | ExternFnDecl, known_types: set[str]) -> bool:
    if len(a.params) != len(b.params):
        return False
    a_typevars = set(getattr(a, "generics", []))
    b_typevars = set(getattr(b, "generics", []))
    for _, pty in a.params:
        if _is_typevar(pty, known_types):
            a_typevars.add(pty)
    for _, pty in b.params:
        if _is_typevar(pty, known_types):
            b_typevars.add(pty)

    strictly_more = False
    for i, ((_, ap), (_, bp)) in enumerate(zip(a.params, b.params)):
        ap_c = _canonical_type(ap)
        bp_c = _canonical_type(bp)
        a_wild = ap_c == "Any" or ap_c in a_typevars
        b_wild = bp_c == "Any" or bp_c in b_typevars

        if i == 0 and _is_ref_type(ap_c):
            inner = _strip_ref(ap_c)
            if inner in a_typevars:
                a_wild = True
        if i == 0 and _is_ref_type(bp_c):
            inner = _strip_ref(bp_c)
            if inner in b_typevars:
                b_wild = True

        if a_wild and not b_wild:
            return False
        if not a_wild and b_wild:
            strictly_more = True
            continue
        if not a_wild and not b_wild and not _same_type(ap_c, bp_c):
            return False

    a_bounds = set(getattr(a, "where_bounds", []))
    b_bounds = set(getattr(b, "where_bounds", []))
    if a_bounds < b_bounds:
        return False
    if a_bounds > b_bounds:
        strictly_more = True
    return strictly_more


def _decl_overlap_probe(a: FnDecl | ExternFnDecl, b: FnDecl | ExternFnDecl, known_types: set[str]) -> list[str] | None:
    if bool(getattr(a, "is_variadic", False)) or bool(getattr(b, "is_variadic", False)):
        return None
    if len(a.params) != len(b.params):
        return None
    probes: list[str] = []
    a_typevars = set(getattr(a, "generics", []))
    b_typevars = set(getattr(b, "generics", []))
    for _, pty in a.params:
        if _is_typevar(pty, known_types):
            a_typevars.add(pty)
    for _, pty in b.params:
        if _is_typevar(pty, known_types):
            b_typevars.add(pty)

    for i, ((_, ap), (_, bp)) in enumerate(zip(a.params, b.params)):
        ap_c = _canonical_type(ap)
        bp_c = _canonical_type(bp)
        a_wild = ap_c == "Any" or ap_c in a_typevars
        b_wild = bp_c == "Any" or bp_c in b_typevars
        if i == 0 and _is_ref_type(ap_c) and _strip_ref(ap_c) in a_typevars:
            a_wild = True
        if i == 0 and _is_ref_type(bp_c) and _strip_ref(bp_c) in b_typevars:
            b_wild = True
        if a_wild and b_wild:
            probes.append("Int")
            continue
        if a_wild and not b_wild:
            probes.append(_strip_ref(bp_c) if i == 0 and _is_ref_type(bp_c) else bp_c)
            continue
        if b_wild and not a_wild:
            probes.append(_strip_ref(ap_c) if i == 0 and _is_ref_type(ap_c) else ap_c)
            continue
        if _same_type(ap_c, bp_c):
            probes.append(_strip_ref(ap_c) if i == 0 and _is_ref_type(ap_c) else ap_c)
            continue
        if i == 0 and _is_ref_type(ap_c) and _same_type(_strip_ref(ap_c), bp_c):
            probes.append(bp_c)
            continue
        if i == 0 and _is_ref_type(bp_c) and _same_type(_strip_ref(bp_c), ap_c):
            probes.append(ap_c)
            continue
        return None
    if _match_decl_bindings(a, probes, known_types) is None:
        return None
    if _match_decl_bindings(b, probes, known_types) is None:
        return None
    return probes


def _decls_overlap(a: FnDecl | ExternFnDecl, b: FnDecl | ExternFnDecl, known_types: set[str]) -> bool:
    return _decl_overlap_probe(a, b, known_types) is not None


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
        bound_rejections: list[tuple[str, str]] = []
        other_rejections: list[tuple[str, str]] = []
        for d in decls:
            sig = _decl_signature_text(d)
            kind, reason = _decl_rejection_reason(d, arg_types, known_types)
            if kind == "bound":
                bound_rejections.append((sig, reason))
            else:
                other_rejections.append((sig, reason))
        if bound_rejections:
            sig, reason = bound_rejections[0]
            raise SemanticError(
                _diag(
                    filename,
                    line,
                    col,
                    (
                        f"trait bound check failed for {name}({', '.join(arg_types)}): {reason}; "
                        f"candidate `{sig}`"
                    ),
                )
            )
        rejection_text = ""
        if other_rejections:
            details = "; ".join(
                f"`{sig}` rejected: {reason}" for sig, reason in other_rejections[:3]
            )
            rejection_text = f"; rejected: {details}"
        available = ", ".join(f"`{_decl_signature_text(d)}`" for d in decls)
        if available:
            raise SemanticError(
                _diag(
                    filename,
                    line,
                    col,
                    f"no matching overload for {name}({', '.join(arg_types)}); available: {available}{rejection_text}",
                )
            )
        raise SemanticError(_diag(filename, line, col, f"no matching overload for {name}({', '.join(arg_types)})"))
    ranked.sort(key=lambda x: x[0], reverse=True)
    best_score = ranked[0][0]
    best = [d for s, d in ranked if s == best_score]
    if len(best) > 1:
        candidates = ", ".join(f"`{_decl_signature_text(d)}`" for d in best)
        raise SemanticError(
            _diag(
                filename,
                line,
                col,
                f"ambiguous overload for {name}({', '.join(arg_types)}): candidates {candidates}",
            )
        )
    return best[0]


def _const_expr_type(expr: Any, known: dict[str, str]) -> str | None:
    if isinstance(expr, BoolLit):
        return "Bool"
    if isinstance(expr, Literal):
        if isinstance(expr.value, bool):
            return "Bool"
        if isinstance(expr.value, int):
            return "Int"
        if isinstance(expr.value, float):
            return "Float"
        if isinstance(expr.value, str):
            return "String"
        return None
    if isinstance(expr, CastExpr):
        return _canonical_type(expr.type_name)
    if isinstance(expr, TypeAnnotated):
        return _canonical_type(expr.type_name)
    if isinstance(expr, Name):
        return known.get(expr.value)
    if isinstance(expr, Unary) and expr.op in {"-", "+"}:
        inner = _const_expr_type(expr.expr, known)
        if inner in {"Int", "Float"} or _is_int_type(inner or "") or _is_float_type(inner or ""):
            return inner
    return None


def _load_imported_program_items(
    importer_file: str,
    import_decl: ImportDecl,
    *,
    seen: set[str],
) -> tuple[list[Any], Path]:
    try:
        resolved_path = resolve_import_path(import_decl, importer_file)
    except Exception as err:
        raise SemanticError(_diag(importer_file, import_decl.line, import_decl.col, str(err))) from err
    key = resolved_path.resolve().as_posix()
    if key in seen:
        return [], resolved_path
    seen.add(key)
    try:
        text = resolved_path.read_text()
    except OSError as err:
        raise SemanticError(_diag(importer_file, import_decl.line, import_decl.col, str(err))) from err
    try:
        imported_prog = parse(text, filename=str(resolved_path))
    except Exception as err:
        raise SemanticError(_diag(importer_file, import_decl.line, import_decl.col, str(err))) from err

    items: list[Any] = list(imported_prog.items)
    for item in items:
        try:
            setattr(item, "_source_filename", str(resolved_path))
        except Exception:
            pass
    for sub in imported_prog.items:
        if not isinstance(sub, ImportDecl):
            continue
        sub_items, _ = _load_imported_program_items(str(resolved_path), sub, seen=seen)
        items.extend(sub_items)
    return items, resolved_path


def analyze(
    prog: Program,
    filename: str = "<input>",
    freestanding: bool = False,
    *,
    require_entrypoint: str | None = None,
    collect_errors: bool = False,
):
    """Run semantic analysis and type/safety checks for a program AST.
    
    Parameters:
        prog: Program AST to read or mutate.
        filename: Filename context used for diagnostics or path resolution.
        freestanding: Whether hosted-runtime features are disallowed.
        require_entrypoint: Input value used by this routine.
        collect_errors: Input value used by this routine.
    
    Returns:
        Value produced by the routine, if any.
    """
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
        traits: dict[str, TraitDecl] = {}
        global_scope: dict[str, str] = {}
        global_mut_scope: dict[str, bool] = {}
        imported_seen: set[str] = set()
        ffi_libs: set[str] = set()
        local_const_types: dict[str, str] = {}
        seen_fn_decls: set[tuple[str, tuple[tuple[str, str], ...], str, bool, bool, bool]] = set()

        work_items: list[tuple[Any, str]] = [(item, filename) for item in prog.items]
        for item in prog.items:
            if not isinstance(item, ImportDecl):
                continue
            try:
                imported_items, resolved_path = _load_imported_program_items(filename, item, seen=imported_seen)
            except SemanticError as err:
                _record(err)
                continue
            if item.alias:
                alias_name = item.alias
                if item.path:
                    alias_name = item.path[-1]
                elif item.source is not None:
                    alias_name = Path(item.source).stem
                global_scope[item.alias] = f"module:{alias_name}"
            for sub_item in imported_items:
                work_items.append((sub_item, str(resolved_path)))

        for item, item_filename in work_items:
            try:
                if isinstance(item, ImportDecl):
                    continue
                if isinstance(item, StructDecl):
                    for _, field_ty in item.fields:
                        _validate_decl_type(field_ty, item_filename, item.line, item.col)
                    if item.packed:
                        for _, field_ty in item.fields:
                            c = _canonical_type(field_ty)
                            if c != "Bool" and not _is_int_type(c):
                                raise SemanticError(_diag(item_filename, item.line, item.col, "packed struct fields must be integer or bool types"))
                    structs[item.name] = item
                    continue
                if isinstance(item, TraitDecl):
                    traits[item.name] = item
                    continue
                if isinstance(item, TypeAliasDecl):
                    _validate_decl_type(item.target, item_filename, item.line, item.col)
                    continue
                if isinstance(item, EnumDecl):
                    enums[item.name] = item
                    continue
                if isinstance(item, LetStmt):
                    if getattr(item, "reassign_if_exists", False):
                        raise SemanticError(_diag(item_filename, item.line, item.col, "top-level assignment requires a prior binding"))
                    if item.mut and not getattr(item, "_decl_unsafe", False):
                        raise SemanticError(_diag(item_filename, item.line, item.col, "top-level mutable bindings require `unsafe mut`"))
                    inferred = item.type_name or _const_expr_type(item.expr, local_const_types)
                    if inferred is None:
                        raise SemanticError(_diag(item_filename, item.line, item.col, f"cannot infer type for top-level binding {item.name}"))
                    _validate_decl_type(inferred, item_filename, item.line, item.col)
                    local_const_types[item.name] = inferred
                    global_scope[item.name] = inferred
                    global_mut_scope[item.name] = bool(item.mut)
                    continue
                if isinstance(item, (FnDecl, ExternFnDecl)):
                    for _, pty in item.params:
                        _validate_decl_type(pty, item_filename, item.line, item.col)
                    _validate_decl_type(item.ret, item_filename, item.line, item.col)
                    key = (
                        item.name,
                        tuple((pn, _canonical_type(pt)) for pn, pt in item.params),
                        _canonical_type(item.ret),
                        bool(getattr(item, "is_variadic", False)),
                        bool(getattr(item, "unsafe", False)),
                        isinstance(item, ExternFnDecl),
                    )
                    if key in seen_fn_decls:
                        continue
                    seen_fn_decls.add(key)
                    if isinstance(item, ExternFnDecl):
                        libs = list(item.link_libs)
                        if not libs and item.lib:
                            libs = [item.lib]
                        item.link_libs = libs
                        for lib in libs:
                            if lib:
                                ffi_libs.add(lib)
                    fn_groups.setdefault(item.name, []).append(item)
            except SemanticError as err:
                _record(err)
                continue

        trait_impls: dict[str, set[str]] = {name: set() for name in traits}

        for decls in fn_groups.values():
            for fn in decls:
                if not isinstance(fn, FnDecl):
                    continue
                if getattr(fn, "gpu_kernel", False):
                    fn_filename = getattr(fn, "_source_filename", filename)
                    if fn.async_fn:
                        _record(
                            SemanticError(
                                _diag(fn_filename, fn.line, fn.col, "gpu kernels cannot be async")
                            )
                        )
                    if fn.unsafe:
                        _record(
                            SemanticError(
                                _diag(fn_filename, fn.line, fn.col, "gpu kernels cannot be unsafe")
                            )
                        )
                    if fn.generics:
                        _record(
                            SemanticError(
                                _diag(fn_filename, fn.line, fn.col, "gpu kernels do not support generic parameters yet")
                            )
                        )
                    if fn.where_bounds:
                        _record(
                            SemanticError(
                                _diag(fn_filename, fn.line, fn.col, "gpu kernels do not support trait bounds on generics")
                            )
                        )
                    if _canonical_type(fn.ret) != "Void":
                        _record(
                            SemanticError(
                                _diag(fn_filename, fn.line, fn.col, "gpu kernels must return Void")
                            )
                        )
                    for pname, pty in fn.params:
                        if not _is_gpu_kernel_param_type(pty, structs):
                            _record(
                                SemanticError(
                                    _diag(
                                        fn_filename,
                                        fn.line,
                                        fn.col,
                                        f"gpu kernel parameter {pname} uses unsupported type {pty}",
                                    )
                                )
                            )
                known_types = set(PRIMITIVES) | set(structs.keys()) | set(enums.keys())
                type_vars = set(fn.generics)
                for _, pty in fn.params:
                    if _is_typevar(pty, known_types):
                        type_vars.add(pty)
                if _is_typevar(fn.ret, known_types):
                    type_vars.add(fn.ret)
                for tvar, trait_name in getattr(fn, "where_bounds", []):
                    if tvar not in type_vars:
                        _record(
                            SemanticError(
                                _diag(
                                    getattr(fn, "_source_filename", filename),
                                    fn.line,
                                    fn.col,
                                    f"generic bound type variable {tvar} is not declared in function generics",
                                )
                            )
                        )
                    if trait_name not in traits:
                        _record(
                            SemanticError(
                                _diag(
                                    getattr(fn, "_source_filename", filename),
                                    fn.line,
                                    fn.col,
                                    f"unknown trait {trait_name} in generic bounds",
                                )
                            )
                        )

        known_types = set(PRIMITIVES) | set(structs.keys()) | set(enums.keys())
        for name, decls in fn_groups.items():
            fn_decls = [d for d in decls if isinstance(d, FnDecl) and not bool(getattr(d, "is_variadic", False))]
            for i, a in enumerate(fn_decls):
                for b in fn_decls[i + 1 :]:
                    probe = _decl_overlap_probe(a, b, known_types)
                    if probe is None:
                        continue
                    if not _where_bounds_satisfied_for_args(
                        a,
                        probe,
                        known_types,
                        traits=traits,
                        fn_groups=fn_groups,
                        trait_impls=trait_impls,
                    ):
                        continue
                    if not _where_bounds_satisfied_for_args(
                        b,
                        probe,
                        known_types,
                        traits=traits,
                        fn_groups=fn_groups,
                        trait_impls=trait_impls,
                    ):
                        continue
                    if _decl_more_specific(a, b, known_types) or _decl_more_specific(b, a, known_types):
                        continue
                    probe_text = ", ".join(probe)
                    _record(
                        SemanticError(
                            _diag(
                                getattr(a, "_source_filename", filename),
                                a.line,
                                a.col,
                                (
                                    f"overlapping overloads for {name} are ambiguous for ({probe_text}): "
                                    f"`{_decl_signature_text(a)}` vs `{_decl_signature_text(b)}`"
                                ),
                            )
                        )
                    )

        prog.ffi_libs = set(sorted(ffi_libs))

        for name, decls in fn_groups.items():
            if len(decls) == 1:
                if isinstance(decls[0], FnDecl):
                    decls[0].symbol = name
                continue
            for i, d in enumerate(decls):
                if isinstance(d, FnDecl):
                    d.symbol = f"{name}__impl{i}"

        if require_entrypoint:
            try:
                entries = [d for d in fn_groups.get(require_entrypoint, []) if isinstance(d, FnDecl)]
                if not entries:
                    if require_entrypoint == "_start":
                        raise SemanticError(_diag(filename, 1, 1, "missing _start()"))
                    raise SemanticError(_diag(filename, 1, 1, "missing main()"))
                if len(entries) != 1:
                    raise SemanticError(
                        _diag(
                            filename,
                            entries[0].line,
                            entries[0].col,
                            f"{require_entrypoint}() must have a single unambiguous declaration",
                        )
                    )
                entry = entries[0]
                if entry.params:
                    raise SemanticError(_diag(filename, entry.line, entry.col, f"{require_entrypoint}() must not take parameters"))
                if require_entrypoint == "main" and _canonical_type(entry.ret) != "Int":
                    raise SemanticError(_diag(filename, entry.line, entry.col, "main() must return Int"))
            except SemanticError as err:
                _record(err)

        _KNOWN_TRAITS_STACK.append(set(traits.keys()))
        _TRAIT_IMPLS_STACK.append({k: set(v) for k, v in trait_impls.items()})
        _TRAITS_STACK.append(dict(traits))
        _FN_GROUPS_STACK.append(fn_groups)
        try:
            for decls in fn_groups.values():
                for fn in decls:
                    if isinstance(fn, ExternFnDecl):
                        continue
                    try:
                        fn_filename = getattr(fn, "_source_filename", filename)
                        _analyze_fn(fn, fn_groups, structs, enums, fn_filename, global_scope, global_mut_scope)
                    except SemanticError as err:
                        _record(err)
                        continue
        finally:
            _FN_GROUPS_STACK.pop()
            _TRAITS_STACK.pop()
            _TRAIT_IMPLS_STACK.pop()
            _KNOWN_TRAITS_STACK.pop()
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
    global_mut_scope: dict[str, bool],
):
    for pname, pty in fn.params:
        _require_sized_value_type(filename, fn.line, fn.col, pty, f"parameter {pname}")
    _require_sized_value_type(filename, fn.line, fn.col, fn.ret, "function return")
    ref_param_names = {pname for pname, pty in fn.params if _is_ref_type(pty)}
    if _is_ref_type(fn.ret) and not ref_param_names:
        raise SemanticError(_diag(filename, fn.line, fn.col, f"function {fn.name} returns a reference but has no reference parameter to tie its lifetime"))
    scopes: list[dict[str, str]] = [global_scope, {n: t for n, t in fn.params}]
    param_mut = dict(getattr(fn, "param_mut", {}))
    mut_scopes: list[dict[str, bool]] = [global_mut_scope, {n: bool(param_mut.get(n, False)) for n, _ in fn.params}]
    owned = _OwnedState()
    borrow = _BorrowState()
    move = _MoveState()
    move.fn_ret = _canonical_type(fn.ret)
    for n, _ in fn.params:
        move.declare(n)
    borrow_scopes: list[set[str]] = [set()]
    move_scopes: list[dict[str, bool | None]] = [{}]
    _check_block(
        fn.body,
        scopes,
        mut_scopes,
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
        bool(getattr(fn, "gpu_kernel", False)),
    )
    if _canonical_type(fn.ret) not in {"Void", "Never"} and not _has_value_return(fn.body):
        raise SemanticError(_diag(filename, fn.line, fn.col, f"function {fn.name} must return {fn.ret}"))
    owned.check_no_live_leaks(fn.name, filename, fn.line, fn.col)


def _has_value_return(body: list[Any]) -> bool:
    for st in body:
        if isinstance(st, ReturnStmt):
            if st.expr is not None:
                return True
            continue
        if isinstance(st, IfStmt):
            if _has_value_return(st.then_body) or _has_value_return(st.else_body):
                return True
            continue
        if isinstance(st, WhileStmt) and _has_value_return(st.body):
            return True
        if isinstance(st, ForStmt) and _has_value_return(st.body):
            return True
        if isinstance(st, ComptimeStmt) and _has_value_return(st.body):
            return True
        if isinstance(st, UnsafeStmt) and _has_value_return(st.body):
            return True
        if isinstance(st, MatchStmt):
            for _, arm in st.arms:
                if _has_value_return(arm):
                    return True
    return False


def _check_block(
    body: list[Any],
    scopes: list[dict[str, str]],
    mut_scopes: list[dict[str, bool]],
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
    gpu_kernel: bool,
):
    for st in body:
        _check_stmt(
            st,
            scopes,
            mut_scopes,
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
            gpu_kernel,
        )
    borrow.release_scope(borrow_scopes[-1])
    move.release_scope(move_scopes[-1])


def _flatten_or_pattern(pat: Any) -> list[Any]:
    if isinstance(pat, OrPattern):
        out: list[Any] = []
        for p in pat.patterns:
            out.extend(_flatten_or_pattern(p))
        return out
    return [pat]


def _split_match_pattern(pat: Any) -> tuple[list[Any], Any | None]:
    if isinstance(pat, GuardedPattern):
        return _flatten_or_pattern(pat.pattern), pat.guard
    return _flatten_or_pattern(pat), None


def _enum_variant_name_for_pattern(pat: Any, enum_name: str) -> str | None:
    if isinstance(pat, FieldExpr) and isinstance(pat.obj, Name) and pat.obj.value == enum_name:
        return pat.field
    if (
        isinstance(pat, Call)
        and isinstance(pat.fn, FieldExpr)
        and isinstance(pat.fn.obj, Name)
        and pat.fn.obj.value == enum_name
    ):
        return pat.fn.field
    return None


def _enum_variant_payload_patterns_for_pattern(pat: Any, enum_name: str) -> list[Any] | None:
    if isinstance(pat, FieldExpr) and isinstance(pat.obj, Name) and pat.obj.value == enum_name:
        return []
    if (
        isinstance(pat, Call)
        and isinstance(pat.fn, FieldExpr)
        and isinstance(pat.fn.obj, Name)
        and pat.fn.obj.value == enum_name
    ):
        return list(pat.args)
    return None


def _enum_decl_for_type(typ: str, enums: dict[str, EnumDecl]) -> EnumDecl | None:
    c = _canonical_type(typ)
    if c in enums:
        return enums[c]
    parsed = _parse_parametric_type(c)
    if parsed is not None and parsed[0] in enums:
        return enums[parsed[0]]
    return None


def _covered_enum_variants_by_pattern(pat: Any, enum_decl: EnumDecl, enums: dict[str, EnumDecl]) -> set[str] | None:
    all_variants = {name for name, _ in enum_decl.variants}
    if isinstance(pat, Name):
        # `_` and any identifier binding are total for the expected enum type.
        return set(all_variants)
    if isinstance(pat, WildcardPattern):
        return set(all_variants)
    variant_name = _enum_variant_name_for_pattern(pat, enum_decl.name)
    if variant_name is None:
        return None
    payload_types = next((vtypes for vname, vtypes in enum_decl.variants if vname == variant_name), None)
    if payload_types is None:
        return None
    payload_pats = _enum_variant_payload_patterns_for_pattern(pat, enum_decl.name)
    if payload_pats is None:
        payload_pats = []
    if len(payload_pats) != len(payload_types):
        return None
    for pnode, pty in zip(payload_pats, payload_types):
        if isinstance(pnode, Name) or isinstance(pnode, WildcardPattern):
            continue
        inner_decl = _enum_decl_for_type(pty, enums)
        if inner_decl is None:
            return None
        inner_cov = _covered_enum_variants_by_pattern(pnode, inner_decl, enums)
        if inner_cov is None:
            return None
        if inner_cov != {name for name, _ in inner_decl.variants}:
            return None
    return {variant_name}


def _finite_axes_for_type(
    typ: str,
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    *,
    seen_structs: set[str] | None = None,
) -> list[tuple[set[str], set[str]]]:
    exp_c = _canonical_type(typ)
    if exp_c == "Bool":
        universe = {"false", "true"}
        return [(set(universe), set(universe))]
    enum_decl = _enum_decl_for_type(exp_c, enums)
    if enum_decl is not None:
        universe = {name for name, _ in enum_decl.variants}
        return [(set(universe), set(universe))]
    if exp_c in structs:
        guard = seen_structs or set()
        if exp_c in guard:
            return []
        guard.add(exp_c)
        axes: list[tuple[set[str], set[str]]] = []
        for _, fty in structs[exp_c].fields:
            axes.extend(_finite_axes_for_type(fty, structs, enums, seen_structs=guard))
        guard.remove(exp_c)
        return axes
    return []


def _coverage_axes_for_pattern(
    pat: Any,
    expected_ty: str,
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
) -> list[tuple[set[str], set[str]]] | None:
    if isinstance(pat, (WildcardPattern, Name)):
        return _finite_axes_for_type(expected_ty, structs, enums)

    exp_c = _canonical_type(expected_ty)
    if exp_c == "Bool":
        if isinstance(pat, BoolLit):
            value = "true" if pat.value else "false"
            return [({value}, {"false", "true"})]
        return None

    enum_decl = _enum_decl_for_type(exp_c, enums)
    if enum_decl is not None:
        variant_name = _enum_variant_name_for_pattern(pat, enum_decl.name)
        if variant_name is None:
            return None
        payload_types = next((vtypes for vname, vtypes in enum_decl.variants if vname == variant_name), None)
        if payload_types is None:
            return None
        payload_pats = _enum_variant_payload_patterns_for_pattern(pat, enum_decl.name)
        if payload_pats is None or len(payload_pats) != len(payload_types):
            return None
        universe = {name for name, _ in enum_decl.variants}
        axes: list[tuple[set[str], set[str]]] = [({variant_name}, universe)]
        for pnode, pty in zip(payload_pats, payload_types):
            inner_axes = _coverage_axes_for_pattern(pnode, pty, structs, enums)
            if inner_axes is None:
                return None
            axes.extend(inner_axes)
        return axes

    if exp_c in structs and isinstance(pat, Call) and isinstance(pat.fn, Name) and pat.fn.value == exp_c:
        decl = structs[exp_c]
        if len(pat.args) != len(decl.fields):
            return None
        axes: list[tuple[set[str], set[str]]] = []
        for pnode, (_, fty) in zip(pat.args, decl.fields):
            inner_axes = _coverage_axes_for_pattern(pnode, fty, structs, enums)
            if inner_axes is None:
                return None
            axes.extend(inner_axes)
        return axes

    # Non-finite domains (e.g., Int/String) are only analyzable when total, which
    # is handled by wildcard/name above.
    return None


def _variant_payload_coverage_keys(
    payload_pats: list[Any],
    payload_types: list[str],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
) -> tuple[set[tuple[str, ...]] | None, set[tuple[str, ...]] | None]:
    axes: list[tuple[set[str], set[str]]] = []
    for pnode, pty in zip(payload_pats, payload_types):
        field_axes = _coverage_axes_for_pattern(pnode, pty, structs, enums)
        if field_axes is None:
            return None, None
        axes.extend(field_axes)
    if not axes:
        return set(), set()
    cov_keys = {tuple(parts) for parts in product(*(sorted(c) for c, _ in axes))}
    full_keys = {tuple(parts) for parts in product(*(sorted(u) for _, u in axes))}
    return cov_keys, full_keys


def _pattern_is_total_for_type(pat: Any, expected_ty: str, structs: dict[str, StructDecl], enums: dict[str, EnumDecl]) -> bool:
    if isinstance(pat, WildcardPattern):
        return True
    if isinstance(pat, Name):
        return True
    exp_c = _canonical_type(expected_ty)
    enum_decl = _enum_decl_for_type(exp_c, enums)
    if enum_decl is not None:
        variant_name = _enum_variant_name_for_pattern(pat, enum_decl.name)
        if variant_name is None:
            return False
        # A single enum constructor never covers the full enum domain unless the
        # pattern itself is a wildcard/binding (handled above).
        return False
    if exp_c in structs and isinstance(pat, Call) and isinstance(pat.fn, Name) and pat.fn.value == exp_c:
        decl = structs[exp_c]
        if len(pat.args) != len(decl.fields):
            return False
        return all(_pattern_is_total_for_type(pp, pty, structs, enums) for pp, (_, pty) in zip(pat.args, decl.fields))
    return False


def _analyze_pattern_against_type(
    pat: Any,
    expected_ty: str,
    scopes: list[dict[str, str]],
    mut_scopes: list[dict[str, bool]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    owned: _OwnedState,
    borrow: _BorrowState,
    move: _MoveState,
    filename: str,
    fn_name: str,
    unsafe_ok: bool,
    gpu_kernel: bool,
    bindings_for_arm: dict[str, str],
) -> None:
    if isinstance(pat, WildcardPattern):
        return
    if isinstance(pat, Name):
        if pat.value == "_":
            return
        prev = bindings_for_arm.get(pat.value)
        exp_c = _canonical_type(expected_ty)
        if prev is not None and not _same_type(prev, exp_c):
            raise SemanticError(
                _diag(
                    filename,
                    pat.line,
                    pat.col,
                    f"pattern binding {pat.value} has conflicting types {prev} and {exp_c}",
                )
            )
        bindings_for_arm[pat.value] = exp_c
        return

    exp_c = _canonical_type(expected_ty)
    enum_decl = _enum_decl_for_type(exp_c, enums)
    if enum_decl is not None:
        variant_name = _enum_variant_name_for_pattern(pat, enum_decl.name)
        if variant_name is not None:
            payload_types = next((vtypes for vname, vtypes in enum_decl.variants if vname == variant_name), None)
            if payload_types is None:
                raise SemanticError(_diag(filename, pat.line, pat.col, f"unknown enum variant {enum_decl.name}.{variant_name}"))
            payload_pats = _enum_variant_payload_patterns_for_pattern(pat, enum_decl.name) or []
            if len(payload_pats) != len(payload_types):
                raise SemanticError(
                    _diag(
                        filename,
                        pat.line,
                        pat.col,
                        f"{enum_decl.name}.{variant_name} pattern expects {len(payload_types)} args, got {len(payload_pats)}",
                    )
                )
            for pnode, pty in zip(payload_pats, payload_types):
                _analyze_pattern_against_type(
                    pnode,
                    pty,
                    scopes,
                    mut_scopes,
                    fn_groups,
                    structs,
                    enums,
                    owned,
                    borrow,
                    move,
                    filename,
                    fn_name,
                    unsafe_ok,
                    gpu_kernel,
                    bindings_for_arm,
                )
            return

    if exp_c in structs and isinstance(pat, Call) and isinstance(pat.fn, Name):
        struct_name = pat.fn.value
        if struct_name != exp_c:
            raise SemanticError(_diag(filename, pat.line, pat.col, f"match pattern expects {exp_c}, got {struct_name}"))
        decl = structs[exp_c]
        if len(pat.args) != len(decl.fields):
            raise SemanticError(
                _diag(
                    filename,
                    pat.line,
                    pat.col,
                    f"{exp_c} pattern expects {len(decl.fields)} args, got {len(pat.args)}",
                )
            )
        for pnode, (_, fty) in zip(pat.args, decl.fields):
            _analyze_pattern_against_type(
                pnode,
                fty,
                scopes,
                mut_scopes,
                fn_groups,
                structs,
                enums,
                owned,
                borrow,
                move,
                filename,
                fn_name,
                unsafe_ok,
                gpu_kernel,
                bindings_for_arm,
            )
        return

    pty = _infer(
        pat,
        scopes,
        mut_scopes,
        fn_groups,
        structs,
        enums,
        owned,
        borrow,
        move,
        filename,
        fn_name,
        unsafe_ok,
        gpu_kernel,
    )
    _require_type(filename, pat.line, pat.col, expected_ty, pty, "match pattern")


def _check_stmt(
    st,
    scopes: list[dict[str, str]],
    mut_scopes: list[dict[str, bool]],
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
    gpu_kernel: bool,
):
    def _is_narrowing_cond(expr: Any) -> tuple[str, str] | None:
        if not (isinstance(expr, Binary) and expr.op == "is"):
            return None
        if not (isinstance(expr.left, Name) and isinstance(expr.right, Name)):
            return None
        return expr.left.value, _canonical_type(expr.right.value)

    if gpu_kernel and isinstance(st, (DeferStmt, ComptimeStmt, UnsafeStmt, DropStmt, MatchStmt)):
        raise SemanticError(
            _diag(
                filename,
                st.line,
                st.col,
                f"{type(st).__name__} is not supported in gpu kernels",
            )
        )

    if isinstance(st, LetStmt):
        if st.name == "_":
            ty = _infer(st.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
            if gpu_kernel and not _is_gpu_safe_type(ty, structs):
                raise SemanticError(_diag(filename, st.line, st.col, f"gpu kernel local `_` uses unsupported type {ty}"))
            _consume_if_move_name(st.expr, ty, borrow, move, filename, st.line, st.col)
            return
        ty = _infer(st.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        if ty == NONE_LIT_TYPE and st.type_name is None:
            raise SemanticError(_diag(filename, st.line, st.col, f"`none` requires explicit nullable type for {st.name}"))
        if st.type_name is not None:
            _require_type(filename, st.line, st.col, st.type_name, ty, st.name)
            ty = st.type_name
        _require_sized_value_type(filename, st.line, st.col, ty, st.name)
        exists = _lookup(st.name, scopes)
        if st.reassign_if_exists and exists is not None:
            synthetic = AssignStmt(
                target=Name(st.name, st.pos, st.line, st.col),
                op="=",
                expr=st.expr,
                pos=st.pos,
                line=st.line,
                col=st.col,
                explicit_set=False,
            )
            _check_stmt(
                synthetic,
                scopes,
                mut_scopes,
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
                gpu_kernel,
            )
            return
        if gpu_kernel and not _is_gpu_safe_type(ty, structs):
            raise SemanticError(_diag(filename, st.line, st.col, f"gpu kernel local {st.name} uses unsupported type {ty}"))
        if st.name in scopes[-1]:
            borrow.release_ref(st.name)
        if st.name not in move_scopes[-1]:
            move_scopes[-1][st.name] = move.moved.get(st.name)
        move.declare(st.name)
        scopes[-1][st.name] = ty
        mut_scopes[-1][st.name] = bool(st.mut)
        borrow_scopes[-1].add(st.name)
        if _is_ref_type(ty):
            if isinstance(st.expr, Unary) and st.expr.op in {"&", "&mut"} and isinstance(st.expr.expr, Name):
                owner = st.expr.expr.value
                owner_mut = bool(_lookup_mut(owner, mut_scopes))
                _ensure_ref_owner_outlives_binding(owner, st.name, scopes, filename, st.line, st.col)
                borrow.bind_ref(st.name, owner, st.expr.op == "&mut", owner_mut, filename, st.line, st.col)
            elif isinstance(st.expr, Name):
                src_ref = borrow.ref_bindings.get(st.expr.value)
                if src_ref is not None:
                    if src_ref.mutable:
                        raise SemanticError(_diag(filename, st.line, st.col, "cannot copy mutable reference"))
                    owner_mut = bool(_lookup_mut(src_ref.owner, mut_scopes))
                    origin = borrow.ref_origins.get(st.expr.value)
                    _ensure_ref_owner_outlives_binding(src_ref.owner, st.name, scopes, filename, st.line, st.col)
                    borrow.bind_ref(st.name, src_ref.owner, False, owner_mut, filename, st.line, st.col, origin=origin)
                elif st.expr.value in ref_param_names:
                    borrow.ref_origins[st.name] = st.expr.value
        if isinstance(st.expr, Name):
            owned.assign_name(st.name, st.expr.value, Span.at(filename, st.line, st.col))
        _consume_if_move_name(st.expr, ty, borrow, move, filename, st.line, st.col)
        if _is_alloc_call(st.expr):
            owned.track_alloc(st.name)
        return
    if isinstance(st, AssignStmt):
        rhs = _infer(st.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        if gpu_kernel and isinstance(st.target, IndexExpr):
            target_obj_ty = _infer(
                st.target.obj,
                scopes,
                mut_scopes,
                fn_groups,
                structs,
                enums,
                owned,
                borrow,
                move,
                filename,
                fn_name,
                unsafe_ok,
                gpu_kernel,
            )
            if _is_gpu_slice_type(target_obj_ty):
                raise SemanticError(_diag(filename, st.line, st.col, "cannot write through immutable GpuSlice<T> in gpu kernel"))
        base = _assign_base_name(st.target)
        if base is not None:
            borrow.check_write(base, filename, st.line, st.col)
        if isinstance(st.target, Name):
            is_mutable = _lookup_mut(st.target.value, mut_scopes)
            if is_mutable is None:
                raise SemanticError(_diag(filename, st.line, st.col, f"assignment to undefined name {st.target.value}"))
            if not is_mutable:
                raise SemanticError(_diag(filename, st.line, st.col, f"cannot assign to immutable binding {st.target.value}"))
            lhs = _lookup(st.target.value, scopes)
            if lhs is None:
                raise SemanticError(_diag(filename, st.line, st.col, f"assignment to undefined name {st.target.value}"))
            if _is_ref_type(lhs) and lhs.startswith("&mut ") and getattr(st, "explicit_set", False):
                inner = lhs[5:]
                _require_type(filename, st.line, st.col, inner, rhs, "set-through-reference")
                return
            _require_compound_assign_compat(filename, st.line, st.col, st.op, lhs, rhs)
            if st.op in {"<<=", ">>="}:
                _require_shift_rhs_static_safe(filename, st.op, lhs, st.expr)
            if _is_ref_type(lhs):
                if isinstance(st.expr, Unary) and st.expr.op in {"&", "&mut"} and isinstance(st.expr.expr, Name):
                    owner = st.expr.expr.value
                    owner_mut = bool(_lookup_mut(owner, mut_scopes))
                    _ensure_ref_owner_outlives_binding(owner, st.target.value, scopes, filename, st.line, st.col)
                    borrow.bind_ref(st.target.value, owner, st.expr.op == "&mut", owner_mut, filename, st.line, st.col)
                elif isinstance(st.expr, Name):
                    src_ref = borrow.ref_bindings.get(st.expr.value)
                    if src_ref is not None:
                        if src_ref.mutable:
                            raise SemanticError(_diag(filename, st.line, st.col, "cannot copy mutable reference"))
                        owner_mut = bool(_lookup_mut(src_ref.owner, mut_scopes))
                        origin = borrow.ref_origins.get(st.expr.value)
                        _ensure_ref_owner_outlives_binding(src_ref.owner, st.target.value, scopes, filename, st.line, st.col)
                        borrow.bind_ref(st.target.value, src_ref.owner, False, owner_mut, filename, st.line, st.col, origin=origin)
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
            _consume_if_move_name(st.expr, rhs, borrow, move, filename, st.line, st.col)
            _assign(st.target.value, lhs, scopes, filename, st.line, st.col)
            move.reinitialize(st.target.value)
            return
        lhs = _infer(st.target, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        _require_compound_assign_compat(filename, st.line, st.col, st.op, lhs, rhs)
        if st.op in {"<<=", ">>="}:
            _require_shift_rhs_static_safe(filename, st.op, lhs, st.expr)
        return
    if isinstance(st, ReturnStmt):
        expr_ty = "Void" if st.expr is None else _infer(st.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        _require_type(filename, st.line, st.col, fn_ret, expr_ty, "return")
        if _is_ref_type(fn_ret) and st.expr is not None:
            tied, note = _ref_return_tie_info(st.expr, ref_param_names, borrow)
            if not tied:
                msg = "returned reference is not tied to an input reference parameter"
                if note:
                    msg = f"{msg}: {note}"
                raise SemanticError(_diag(filename, st.line, st.col, msg))
        if isinstance(st.expr, Name):
            owned.invalidate(st.expr.value)
        if st.expr is not None:
            _consume_if_move_name(st.expr, expr_ty, borrow, move, filename, st.line, st.col)
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
        _infer(st.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        return
    if isinstance(st, ComptimeStmt):
        _check_block(
            st.body,
            scopes + [{}],
            mut_scopes + [{}],
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
            gpu_kernel,
        )
        return
    if isinstance(st, UnsafeStmt):
        _check_block(
            st.body,
            scopes + [{}],
            mut_scopes + [{}],
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
            gpu_kernel,
        )
        return
    if isinstance(st, IfStmt):
        cond_ty = _infer(st.cond, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        _require_type(filename, st.line, st.col, "Bool", cond_ty, "if condition")
        then_owned = owned.copy()
        then_scopes = scopes + [{}]
        then_mut_scopes = mut_scopes + [{}]
        then_borrow = borrow.copy()
        then_move = move.copy()
        then_borrow_scopes = borrow_scopes + [set()]
        then_move_scopes = move_scopes + [{}]
        narrow = _is_narrowing_cond(st.cond)
        if narrow is not None:
            n_name, n_type = narrow
            cur_ty = _lookup(n_name, scopes)
            if cur_ty is not None and _is_union_type(cur_ty):
                if any(_same_type(n_type, m) for m in _union_members(cur_ty)):
                    then_scopes[-1][n_name] = n_type
        _check_block(
            st.then_body,
            then_scopes,
            then_mut_scopes,
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
            gpu_kernel,
        )
        else_owned = owned.copy()
        else_scopes = scopes + [{}]
        else_mut_scopes = mut_scopes + [{}]
        else_borrow = borrow.copy()
        else_move = move.copy()
        else_borrow_scopes = borrow_scopes + [set()]
        else_move_scopes = move_scopes + [{}]
        if narrow is not None:
            n_name, n_type = narrow
            cur_ty = _lookup(n_name, scopes)
            if cur_ty is not None and _is_union_type(cur_ty):
                else_scopes[-1][n_name] = _remove_member_from_union(cur_ty, n_type)
        _check_block(
            st.else_body,
            else_scopes,
            else_mut_scopes,
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
            gpu_kernel,
        )
        owned.merge(then_owned, else_owned)
        borrow.merge(then_borrow, else_borrow)
        move.merge(then_move, else_move)
        return
    if isinstance(st, WhileStmt):
        cond_ty = _infer(st.cond, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        _require_type(filename, st.line, st.col, "Bool", cond_ty, "while condition")
        loop_owned = owned.copy()
        loop_scopes = scopes + [{}]
        loop_mut_scopes = mut_scopes + [{}]
        loop_borrow = borrow.copy()
        loop_move = move.copy()
        loop_borrow_scopes = borrow_scopes + [set()]
        loop_move_scopes = move_scopes + [{}]
        _check_block(
            st.body,
            loop_scopes,
            loop_mut_scopes,
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
            gpu_kernel,
        )
        owned.merge(owned, loop_owned)
        borrow.merge(borrow, loop_borrow)
        move.merge(move, loop_move)
        return
    if isinstance(st, ForStmt):
        loop_var_ty: str
        if isinstance(st.iterable, RangeExpr):
            start_ty = _infer(st.iterable.start, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
            end_ty = _infer(st.iterable.end, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
            if not _is_int_type(start_ty) or not _is_int_type(end_ty):
                raise SemanticError(_diag(filename, st.line, st.col, "range for-in expects integer bounds"))
            _require_type(filename, st.line, st.col, start_ty, end_ty, "for-in range bounds")
            loop_var_ty = _canonical_type(start_ty)
        else:
            iterable_ty = _infer(st.iterable, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
            base_ty = _strip_ref(_canonical_type(iterable_ty))
            if _is_vec_type(base_ty):
                loop_var_ty = _vec_inner(base_ty)
            elif _is_slice_type(base_ty):
                loop_var_ty = _slice_inner(base_ty)
            else:
                raise SemanticError(_diag(filename, st.line, st.col, f"type {iterable_ty} is not iterable"))
            if not _is_copy_type(loop_var_ty):
                raise SemanticError(
                    _diag(
                        filename,
                        st.line,
                        st.col,
                        f"for-in over {iterable_ty} currently requires Copy element type, got {loop_var_ty}",
                    )
                )
        if gpu_kernel and not _is_gpu_safe_type(loop_var_ty, structs):
            raise SemanticError(_diag(filename, st.line, st.col, f"gpu kernel loop variable {st.var} uses unsupported type {loop_var_ty}"))
        loop_scopes = scopes + [{}]
        loop_mut_scopes = mut_scopes + [{}]
        loop_owned = owned.copy()
        loop_borrow = borrow.copy()
        loop_move = move.copy()
        loop_borrow_scopes = borrow_scopes + [set()]
        loop_move_scopes = move_scopes + [{}]
        loop_scopes[-1][st.var] = loop_var_ty
        loop_mut_scopes[-1][st.var] = False
        loop_move_scopes[-1][st.var] = loop_move.moved.get(st.var, False)
        _check_block(
            st.body,
            loop_scopes,
            loop_mut_scopes,
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
            gpu_kernel,
        )
        owned.merge(owned, loop_owned)
        borrow.merge(borrow, loop_borrow)
        move.merge(move, loop_move)
        return
    if isinstance(st, MatchStmt):
        subject_ty = _infer(st.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        seen_bool: set[bool] = set()
        seen_enum_variants: set[str] = set()
        nested_enum_coverage: dict[str, set[tuple[str, ...]]] = {}
        nested_enum_universe: dict[str, set[tuple[str, ...]]] = {}
        subject_enum_decl: EnumDecl | None = None
        subject_canon = _canonical_type(subject_ty)
        if subject_canon in enums:
            subject_enum_decl = enums[subject_canon]
        else:
            parsed_subject = _parse_parametric_type(subject_canon)
            if parsed_subject is not None and parsed_subject[0] in enums:
                subject_enum_decl = enums[parsed_subject[0]]
        seen_catch_all = False
        for idx, (pat, body) in enumerate(st.arms):
            patterns, guard_expr = _split_match_pattern(pat)
            if guard_expr is not None:
                gty = _infer(
                    guard_expr,
                    scopes,
                    mut_scopes,
                    fn_groups,
                    structs,
                    enums,
                    owned,
                    borrow,
                    move,
                    filename,
                    fn_name,
                    unsafe_ok,
                    gpu_kernel,
                )
                _require_type(filename, st.line, st.col, "Bool", gty, "match guard")

            wildcard_count = sum(1 for p in patterns if isinstance(p, WildcardPattern))
            if wildcard_count > 0 and len(patterns) > 1:
                raise SemanticError(
                    _diag(filename, pat.line, pat.col, "wildcard pattern `_` cannot be combined with `|` alternatives")
                )
            has_unconditional_wildcard = wildcard_count == 1 and guard_expr is None
            if has_unconditional_wildcard:
                if seen_catch_all:
                    raise SemanticError(_diag(filename, pat.line, pat.col, "duplicate wildcard match arm"))
                if idx != len(st.arms) - 1:
                    raise SemanticError(_diag(filename, pat.line, pat.col, "wildcard match arm must be last"))
                seen_catch_all = True

            total_alt_count = 0
            for alt_pat in patterns:
                if guard_expr is None and _pattern_is_total_for_type(alt_pat, subject_ty, structs, enums):
                    total_alt_count += 1
            if total_alt_count > 0 and len(patterns) > 1:
                raise SemanticError(
                    _diag(filename, pat.line, pat.col, "catch-all pattern cannot be combined with `|` alternatives")
                )
            has_unconditional_catch_all = total_alt_count > 0 and guard_expr is None and not has_unconditional_wildcard
            if has_unconditional_catch_all:
                if seen_catch_all:
                    raise SemanticError(_diag(filename, pat.line, pat.col, "duplicate catch-all match arm"))
                if idx != len(st.arms) - 1:
                    raise SemanticError(_diag(filename, pat.line, pat.col, "catch-all match arm must be last"))
                seen_catch_all = True

            for alt_pat in patterns:
                if isinstance(alt_pat, WildcardPattern):
                    continue
                handled_enum_pattern = False
                if subject_enum_decl is not None:
                    enum_name = subject_enum_decl.name
                    variant_name = _enum_variant_name_for_pattern(alt_pat, enum_name)
                    if variant_name is not None:
                        handled_enum_pattern = True
                if guard_expr is None and isinstance(alt_pat, BoolLit):
                    if alt_pat.value in seen_bool:
                        value_text = "true" if alt_pat.value else "false"
                        raise SemanticError(_diag(filename, alt_pat.line, alt_pat.col, f"duplicate Bool match arm for {value_text}"))
                    seen_bool.add(alt_pat.value)
                if guard_expr is None and subject_enum_decl is not None:
                    enum_name = subject_enum_decl.name
                    variant_name = _enum_variant_name_for_pattern(alt_pat, enum_name)
                    if variant_name is not None:
                        known = {name for name, _ in subject_enum_decl.variants}
                        if variant_name not in known:
                            raise SemanticError(
                                _diag(filename, alt_pat.line, alt_pat.col, f"unknown enum variant {enum_name}.{variant_name}")
                            )
                        payload_types = next(vtypes for vname, vtypes in subject_enum_decl.variants if vname == variant_name)
                        payload_pats = _enum_variant_payload_patterns_for_pattern(alt_pat, enum_name)
                        if payload_pats is None:
                            payload_pats = []
                        if len(payload_pats) != len(payload_types):
                            raise SemanticError(
                                _diag(
                                    filename,
                                    alt_pat.line,
                                    alt_pat.col,
                                    f"{enum_name}.{variant_name} pattern expects {len(payload_types)} args, got {len(payload_pats)}",
                                )
                            )
                        bindings_for_arm: dict[str, str] = {}
                        for pnode, pty in zip(payload_pats, payload_types):
                            _analyze_pattern_against_type(
                                pnode,
                                pty,
                                scopes,
                                mut_scopes,
                                fn_groups,
                                structs,
                                enums,
                                owned,
                                borrow,
                                move,
                                filename,
                                fn_name,
                                unsafe_ok,
                                gpu_kernel,
                                bindings_for_arm,
                            )
                        variant_total = all(
                            _pattern_is_total_for_type(pnode, pty, structs, enums) for pnode, pty in zip(payload_pats, payload_types)
                        )
                        if variant_total:
                            if variant_name in seen_enum_variants:
                                raise SemanticError(
                                    _diag(filename, alt_pat.line, alt_pat.col, f"duplicate enum match arm for {enum_name}.{variant_name}")
                                )
                            seen_enum_variants.add(variant_name)
                        else:
                            cov_keys, full_keys = _variant_payload_coverage_keys(payload_pats, payload_types, structs, enums)
                            if cov_keys is not None and full_keys is not None and full_keys:
                                nested_enum_universe.setdefault(variant_name, full_keys)
                                current = nested_enum_coverage.setdefault(variant_name, set())
                                if cov_keys.issubset(current):
                                    raise SemanticError(
                                        _diag(
                                            filename,
                                            alt_pat.line,
                                            alt_pat.col,
                                            f"duplicate enum payload match arm for {enum_name}.{variant_name}",
                                        )
                                    )
                                current.update(cov_keys)
                                if current == nested_enum_universe.get(variant_name, set()):
                                    if variant_name in seen_enum_variants:
                                        raise SemanticError(
                                            _diag(
                                                filename,
                                                alt_pat.line,
                                                alt_pat.col,
                                                f"duplicate enum match arm for {enum_name}.{variant_name}",
                                            )
                                        )
                                    seen_enum_variants.add(variant_name)
                        setattr(alt_pat, "_pattern_bindings", bindings_for_arm)
                        continue
                if handled_enum_pattern:
                    continue
                bindings_for_arm = {}
                _analyze_pattern_against_type(
                    alt_pat,
                    subject_ty,
                    scopes,
                    mut_scopes,
                    fn_groups,
                    structs,
                    enums,
                    owned,
                    borrow,
                    move,
                    filename,
                    fn_name,
                    unsafe_ok,
                    gpu_kernel,
                    bindings_for_arm,
                )
                setattr(alt_pat, "_pattern_bindings", bindings_for_arm)
            arm_scopes = scopes + [{}]
            arm_mut_scopes = mut_scopes + [{}]
            arm_borrow_scopes = borrow_scopes + [set()]
            arm_move_scopes = move_scopes + [{}]
            for alt_pat in patterns:
                for bname, bty in getattr(alt_pat, "_pattern_bindings", {}).items():
                    if bname in arm_scopes[-1]:
                        raise SemanticError(_diag(filename, alt_pat.line, alt_pat.col, f"duplicate pattern binding {bname}"))
                    arm_scopes[-1][bname] = bty
                    arm_mut_scopes[-1][bname] = False
            _check_block(
                body,
                arm_scopes,
                arm_mut_scopes,
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
                gpu_kernel,
            )
        if subject_ty == "Bool" and not seen_catch_all and seen_bool != {True, False}:
            raise SemanticError(_diag(filename, st.line, st.col, "non-exhaustive match for Bool"))
        if subject_enum_decl is not None and not seen_catch_all:
            all_variants = {name for name, _ in subject_enum_decl.variants}
            if seen_enum_variants != all_variants:
                missing = ", ".join(sorted(all_variants - seen_enum_variants))
                detail_parts: list[str] = []
                for variant_name in sorted(all_variants - seen_enum_variants):
                    full_keys = nested_enum_universe.get(variant_name)
                    if not full_keys:
                        continue
                    covered = nested_enum_coverage.get(variant_name, set())
                    missing_keys = sorted(full_keys - covered)
                    if not missing_keys:
                        continue
                    preview = ", ".join(
                        "/".join(parts) if parts else "<all>"
                        for parts in missing_keys[:3]
                    )
                    if len(missing_keys) > 3:
                        preview = f"{preview} (+{len(missing_keys) - 3} more)"
                    detail_parts.append(f"{variant_name} payload combinations missing: {preview}")
                detail = ""
                if detail_parts:
                    detail = "; " + "; ".join(detail_parts)
                raise SemanticError(
                    _diag(
                        filename,
                        st.line,
                        st.col,
                        f"non-exhaustive match for enum {subject_enum_decl.name}; missing variants: {missing}{detail}",
                    )
                )
        return
    if isinstance(st, ExprStmt):
        _infer(st.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        if _is_free_call(st.expr):
            ptr = st.expr.args[0]
            if not isinstance(ptr, Name):
                raise SemanticError(_diag(filename, st.line, st.col, "free() expects a named owner"))
            owned.free(ptr.value, Span.at(filename, st.line, st.col))
        return
    if isinstance(st, DropStmt):
        expr_ty = _infer(st.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        _consume_if_move_name(st.expr, expr_ty, borrow, move, filename, st.line, st.col)
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
    mut_scopes: list[dict[str, bool]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    owned: _OwnedState | None,
    borrow: _BorrowState,
    move: _MoveState,
    filename: str,
    fn_name: str,
    unsafe_ok: bool,
    gpu_kernel: bool,
):
    if isinstance(e, WildcardPattern):
        raise SemanticError(_diag(filename, e.line, e.col, "wildcard pattern `_` is only valid in match arms"))
    if isinstance(e, OrPattern):
        raise SemanticError(_diag(filename, e.line, e.col, "or-patterns are only valid in match arms"))
    if isinstance(e, GuardedPattern):
        raise SemanticError(_diag(filename, e.line, e.col, "match guards are only valid in match arms"))
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
            ref_info = borrow.ref_bindings.get(e.value)
            if ref_info is not None:
                move.check_use(ref_info.owner, filename, e.line, e.col)
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
            base = _builtin_base_name(e.value)
            if gpu_kernel and base not in GPU_ALLOWED_IN_KERNEL_BUILTINS:
                raise SemanticError(_diag(filename, e.line, e.col, f"builtin {base} is not available in gpu kernels"))
            _require_freestanding_builtin_allowed(e.value, filename, e.line, e.col)
            if sig.args is None:
                return _typed(e, "Any")
            return _typed(e, f"fn({', '.join(sig.args)}) {sig.ret}")
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
        val_ty = _infer(e.expr, scopes, mut_scopes, fn_groups, structs, enums, owned_copy, borrow_copy, move_copy, filename, fn_name, unsafe_ok, gpu_kernel)
        try:
            layout_of_type(val_ty, structs, mode="query")
        except LayoutError as err:
            raise SemanticError(_diag(filename, e.line, e.col, str(err))) from err
        setattr(e, "query_type", _canonical_type(val_ty))
        return _typed(e, "Int")
    if isinstance(e, AwaitExpr):
        if gpu_kernel:
            raise SemanticError(_diag(filename, e.line, e.col, "await is not supported in gpu kernels"))
        return _typed(e, _infer(e.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel))
    if isinstance(e, TryExpr):
        if gpu_kernel:
            raise SemanticError(_diag(filename, e.line, e.col, "try propagation (`!`) is not supported in gpu kernels"))
        src_ty = _infer(e.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        fn_ret = _canonical_type(getattr(move, "fn_ret", ""))
        src_c = _canonical_type(src_ty)
        if _is_union_type(src_c):
            members = _union_members(src_c)
            if len(members) < 2:
                raise SemanticError(_diag(filename, e.line, e.col, f"`!` expects a fallible union operand, got {src_ty}"))
            ok_ty = members[0]
            err_tys = members[1:]
            fn_members = set(_union_members(fn_ret))
            for et in err_tys:
                if et not in fn_members:
                    raise SemanticError(_diag(filename, e.line, e.col, f"`!` requires function return to include propagated branch `{et}`, got {fn_ret or '<unknown>'}"))
            setattr(e, "try_kind", "union")
            setattr(e, "try_error_types", err_tys)
            return _typed(e, ok_ty)
        raise SemanticError(_diag(filename, e.line, e.col, f"`!` expects a fallible union operand, got {src_ty}"))
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
            owner_mut = bool(_lookup_mut(owner, mut_scopes))
            borrow.ensure_can_borrow(owner, e.op == "&mut", owner_mut, filename, e.line, e.col)
            if e.op == "&mut":
                return _typed(e, f"&mut {owner_ty}")
            return _typed(e, f"&{owner_ty}")
        inner = _infer(e.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        if e.op == "!":
            _require_type(filename, e.line, e.col, "Bool", inner, "unary !")
            return _typed(e, "Bool")
        if e.op == "-":
            if inner != "Any" and not _is_numeric_scalar_type(inner):
                raise SemanticError(_diag(filename, e.line, e.col, f"unary - expects number, got {inner}"))
            
            # NEW: Validate range for negated integer literals
            int_info = _int_info(inner)
            if int_info and isinstance(e.expr, CastExpr) and isinstance(e.expr.expr, Literal) and isinstance(e.expr.expr.value, int):
                bits, signed = int_info
                literal_value = -e.expr.expr.value  # Apply negation
                
                if signed:
                    min_val = -(1 << (bits - 1))
                    max_val = (1 << (bits - 1)) - 1
                else:
                    min_val = 0
                    max_val = (1 << bits) - 1
                
                if literal_value < min_val or literal_value > max_val:
                    raise SemanticError(_diag(filename, e.line, e.col, 
                        f"literal {literal_value} out of range for {inner} (expected {min_val}..{max_val})"))
            
            return _typed(e, inner)
        if e.op == "*":
            if not _is_ref_type(inner):
                raise SemanticError(_diag(filename, e.line, e.col, f"cannot dereference non-reference type {inner}"))
            return _typed(e, _strip_ref(inner))
        return _typed(e, inner)
    if isinstance(e, CastExpr):
        src = _infer(e.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        dst = _canonical_type(e.type_name)
        _validate_decl_type(dst, filename, e.line, e.col)
        src_c = _canonical_type(src)
        
        # Range validation for CastExpr literals (only when NOT negated)
        # Negated literals are handled at the Unary level
        # Check if we're inside a Unary negation by looking at the call stack context
        int_info = _int_info(dst)
        if int_info and isinstance(e.expr, Literal) and isinstance(e.expr.value, int):
            bits, signed = int_info
            literal_value = e.expr.value
            
            if signed:
                min_val = -(1 << (bits - 1))
                max_val = (1 << (bits - 1)) - 1
            else:
                min_val = 0
                max_val = (1 << bits) - 1
            
            # For signed types, allow the absolute value to be one step beyond the range
            # to handle negation. The actual negated value will be checked at Unary level.
            if signed and literal_value > max_val + 1:
                raise SemanticError(_diag(filename, e.line, e.col, 
                    f"literal {literal_value} out of range for {dst} (expected {min_val}..{max_val})"))
            elif not signed and (literal_value < min_val or literal_value > max_val):
                raise SemanticError(_diag(filename, e.line, e.col, 
                    f"literal {literal_value} out of range for {dst} (expected {min_val}..{max_val})"))
        
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
        src = _infer(e.expr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        dst = _canonical_type(e.type_name)
        
        # NEW: Validate literal ranges for arbitrary width integers
        int_info = _int_info(dst)
        if int_info:
            bits, signed = int_info
            
            # Handle both direct literals and negated literals
            literal_value = None
            if isinstance(e.expr, Literal) and isinstance(e.expr.value, int):
                literal_value = e.expr.value
            elif isinstance(e.expr, Unary) and e.expr.op == "-" and isinstance(e.expr.expr, Literal) and isinstance(e.expr.expr.value, int):
                # Handle -5u7 case: Unary("-", TypeAnnotated(Literal(5), "u7"))
                literal_value = -e.expr.expr.value
            elif isinstance(e.expr, Unary) and e.expr.op == "-" and isinstance(e.expr.expr, CastExpr) and isinstance(e.expr.expr.expr, Literal) and isinstance(e.expr.expr.expr.value, int):
                # Handle -5u7 case: Unary("-", CastExpr(Literal(5), "u7"))
                literal_value = -e.expr.expr.expr.value
            
            if literal_value is not None:
                if signed:
                    min_val = -(1 << (bits - 1))
                    max_val = (1 << (bits - 1)) - 1
                else:
                    min_val = 0
                    max_val = (1 << bits) - 1
                
                if literal_value < min_val or literal_value > max_val:
                    raise SemanticError(_diag(filename, e.line, e.col, 
                        f"literal {literal_value} out of range for {dst} (expected {min_val}..{max_val})"))
        
        _validate_decl_type(dst, filename, e.line, e.col)
        _require_type(filename, e.line, e.col, dst, src, "type annotation")
        return _typed(e, dst)
    if isinstance(e, Binary):
        l = _infer(e.left, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        # For 'is' operator, right side is a type name, not an expression to infer
        if e.op == "is":
            return _typed(e, "Bool")
        r = _infer(e.right, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        l_eff = _strip_ref(l)
        r_eff = _strip_ref(r)
        if e.op in {"+", "-", "*", "/", "%"}:
            if e.op == "+" and _is_text_type(l_eff) and _is_text_type(r_eff):
                return _typed(e, "String")
            if _is_int_type(l_eff) and _is_int_type(r_eff):
                _require_strict_int_operands(filename, e.line, e.col, e.op, l_eff, r_eff)
                return _typed(e, _canonical_type(l_eff))
            if _is_float_type(l_eff) and _is_float_type(r_eff):
                return _typed(e, _canonical_type(l_eff))
            if (_is_int_type(l_eff) and _is_float_type(r_eff)) or (_is_float_type(l_eff) and _is_int_type(r_eff)):
                raise SemanticError(_diag(filename, e.line, e.col, f"mixed int/float arithmetic requires explicit cast for operator {e.op}"))
            raise SemanticError(_diag(filename, e.line, e.col, f"numeric operator {e.op} expects numeric operands"))
        if e.op in {"&", "|", "^", "<<", ">>"}:
            _require_strict_int_operands(filename, e.line, e.col, e.op, l_eff, r_eff)
            if e.op in {"<<", ">>"}:
                _require_shift_rhs_static_safe(filename, e.op, l_eff, e.right)
            return _typed(e, _canonical_type(l_eff))
        if e.op in {"==", "!=", "<", "<=", ">", ">="}:
            if _is_int_type(l_eff) and _is_int_type(r_eff):
                _require_strict_int_operands(filename, e.line, e.col, e.op, l_eff, r_eff)
                # Enhanced checks for suspicious signed/unsigned comparisons
                l_info = _int_info(l_eff)
                r_info = _int_info(r_eff)
                if l_info and r_info and l_info[1] != r_info[1]:  # Different signedness
                    # This could be a warning about signed/unsigned comparison
                    pass  # Could add a warning here
            elif (_is_int_type(l_eff) and _is_float_type(r_eff)) or (_is_float_type(l_eff) and _is_int_type(r_eff)):
                raise SemanticError(_diag(filename, e.line, e.col, f"mixed int/float comparison requires explicit cast for operator {e.op}"))
            return _typed(e, "Bool")
        if e.op in {"&&", "||"}:
            _require_type(filename, e.line, e.col, "Bool", l, f"{e.op} left operand")
            _require_type(filename, e.line, e.col, "Bool", r, f"{e.op} right operand")
            return _typed(e, "Bool")
        if e.op == "??":
            if l == NONE_LIT_TYPE:
                return _typed(e, r)
            if not _is_nullable_union(l):
                raise SemanticError(_diag(filename, e.line, e.col, "left operand of ?? must be nullable"))
            inner = _remove_none_from_union(l)
            _require_type(filename, e.line, e.col, inner, r, "?? right operand")
            return _typed(e, inner)
        return _typed(e, "Any")
    if isinstance(e, Call):
        return _typed(e, _infer_call(e, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel))
    if isinstance(e, IndexExpr):
        obj_ty = _infer(e.obj, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        idx_ty = _infer(e.index, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
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
        if _is_gpu_memory_type(base_ty):
            inner = _gpu_element_type(base_ty)
            if inner is not None:
                return _typed(e, inner)
        return _typed(e, "Any")
    if isinstance(e, FieldExpr):
        if isinstance(e.obj, Name) and _lookup(e.obj.value, scopes) is None and e.obj.value in enums:
            enum_decl = enums[e.obj.value]
            variant = next((v for v, _ in enum_decl.variants if v == e.field), None)
            if variant is None:
                raise SemanticError(_diag(filename, e.line, e.col, f"unknown enum variant {e.obj.value}.{e.field}"))
            payload = next(vtypes for vname, vtypes in enum_decl.variants if vname == e.field)
            if payload:
                ret = enum_decl.name
                if enum_decl.generics:
                    ret = f"{enum_decl.name}<{', '.join('Any' for _ in enum_decl.generics)}>"
                return _typed(e, f"fn({', '.join(payload)}) {ret}")
            ret = enum_decl.name
            if enum_decl.generics:
                ret = f"{enum_decl.name}<{', '.join('Any' for _ in enum_decl.generics)}>"
            return _typed(e, ret)
        obj_ty = _infer(e.obj, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        # Strip reference types to get the underlying struct type
        base_ty = _strip_ref(obj_ty)
        if base_ty in structs:
            for fname, fty in structs[base_ty].fields:
                if fname == e.field:
                    return _typed(e, fty)
        if _is_gpu_memory_type(base_ty) and e.field == "len":
            return _typed(e, "fn() Int")
        return _typed(e, "Any")
    if isinstance(e, ArrayLit):
        if not e.elements:
            return _typed(e, "[Any]")
        first_ty = _infer(e.elements[0], scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        for el in e.elements[1:]:
            ety = _infer(el, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
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
            ety = _infer(fexpr, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
            _require_type(filename, getattr(fexpr, "line", e.line), getattr(fexpr, "col", e.col), fty, ety, f"field {fname} of {e.name}")
        return _typed(e, e.name)
    return _typed(e, "Any")


def _check_call_arg_borrows(
    args: list[Any],
    mut_scopes: list[dict[str, bool]],
    borrow: _BorrowState,
    filename: str,
):
    temp = borrow.copy()
    for arg in args:
        if not (isinstance(arg, Unary) and arg.op in {"&", "&mut"} and isinstance(arg.expr, Name)):
            continue
        owner = arg.expr.value
        owner_mut = bool(_lookup_mut(owner, mut_scopes))
        mutable = arg.op == "&mut"
        temp.ensure_can_borrow(owner, mutable, owner_mut, filename, arg.line, arg.col)
        if mutable:
            temp.mutable_borrowed.add(owner)
        else:
            temp.shared_counts[owner] = temp.shared_counts.get(owner, 0) + 1


def _infer_gpu_namespace_call(
    e: Call,
    method: str,
    arg_types: list[str],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    filename: str,
    gpu_kernel: bool,
) -> str:
    if method in GPU_KERNEL_BUILTINS:
        if not gpu_kernel:
            raise SemanticError(_diag(filename, e.line, e.col, f"gpu.{method}() is only valid inside gpu kernels"))
        if len(e.args) != 0:
            raise SemanticError(_diag(filename, e.line, e.col, f"gpu.{method} expects 0 args, got {len(e.args)}"))
        if method == "barrier":
            return "Void"
        return "Int"

    if method not in GPU_HOST_APIS:
        raise SemanticError(_diag(filename, e.line, e.col, f"unknown gpu API gpu.{method}"))
    if gpu_kernel:
        raise SemanticError(_diag(filename, e.line, e.col, f"gpu.{method}() is host-only and cannot run inside gpu kernels"))

    if method == "available":
        if len(e.args) != 0:
            raise SemanticError(_diag(filename, e.line, e.col, f"gpu.available expects 0 args, got {len(e.args)}"))
        return "Bool"
    if method == "device_count":
        if len(e.args) != 0:
            raise SemanticError(_diag(filename, e.line, e.col, f"gpu.device_count expects 0 args, got {len(e.args)}"))
        return "Int"
    if method == "device_name":
        if len(e.args) != 1:
            raise SemanticError(_diag(filename, e.line, e.col, f"gpu.device_name expects 1 args, got {len(e.args)}"))
        _require_type(filename, e.args[0].line, e.args[0].col, "Int", arg_types[0], "arg 0 for gpu.device_name")
        return "String"
    if method == "alloc":
        if len(e.args) != 1:
            raise SemanticError(_diag(filename, e.line, e.col, f"gpu.alloc expects 1 args, got {len(e.args)}"))
        _require_type(filename, e.args[0].line, e.args[0].col, "Int", arg_types[0], "arg 0 for gpu.alloc")
        return "GpuBuffer<Any>"
    if method == "copy":
        if len(e.args) != 1:
            raise SemanticError(_diag(filename, e.line, e.col, f"gpu.copy expects 1 args, got {len(e.args)}"))
        src_ty = _canonical_type(arg_types[0])
        if _is_slice_type(src_ty):
            return f"GpuBuffer<{_slice_inner(src_ty)}>"
        if _is_vec_type(src_ty):
            return f"GpuBuffer<{_vec_inner(src_ty)}>"
        raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"gpu.copy expects [T] or Vec<T>, got {src_ty}"))
    if method == "read":
        if len(e.args) != 1:
            raise SemanticError(_diag(filename, e.line, e.col, f"gpu.read expects 1 args, got {len(e.args)}"))
        src_ty = _canonical_type(arg_types[0])
        inner = _gpu_element_type(src_ty)
        if inner is None:
            raise SemanticError(_diag(filename, e.args[0].line, e.args[0].col, f"gpu.read expects GpuBuffer<T>/GpuSlice<T>/GpuMutSlice<T>, got {src_ty}"))
        return f"[{inner}]"

    # gpu.launch(kernel, grid_size, block_size, ...args)
    if len(e.args) < 3:
        raise SemanticError(_diag(filename, e.line, e.col, "gpu.launch expects at least 3 args: kernel, grid_size, block_size"))
    _require_type(filename, e.args[1].line, e.args[1].col, "Int", arg_types[1], "arg 1 for gpu.launch")
    _require_type(filename, e.args[2].line, e.args[2].col, "Int", arg_types[2], "arg 2 for gpu.launch")

    kernel_expr = e.args[0]
    launch_arg_types = arg_types[3:]
    launch_args = e.args[3:]
    if isinstance(kernel_expr, Name) and kernel_expr.value in fn_groups:
        kernel_name = kernel_expr.value
        candidates = [
            d for d in fn_groups[kernel_name] if isinstance(d, FnDecl) and bool(getattr(d, "gpu_kernel", False))
        ]
        if not candidates:
            raise SemanticError(_diag(filename, kernel_expr.line, kernel_expr.col, f"gpu.launch expects a gpu fn kernel, got `{kernel_name}`"))
        matching: list[FnDecl] = []
        for cand in candidates:
            if len(cand.params) != len(launch_arg_types):
                continue
            if all(_gpu_launch_arg_compatible(pty, aty) for (_, pty), aty in zip(cand.params, launch_arg_types)):
                matching.append(cand)
        if not matching:
            sig = ", ".join(launch_arg_types)
            raise SemanticError(_diag(filename, e.line, e.col, f"no matching gpu kernel overload for launch {kernel_name}({sig})"))
        if len(matching) > 1:
            raise SemanticError(_diag(filename, e.line, e.col, f"ambiguous gpu kernel overload for launch {kernel_name}"))
        chosen = matching[0]
        for i, ((_, expected), arg, aty) in enumerate(zip(chosen.params, launch_args, launch_arg_types), start=3):
            if not _gpu_launch_arg_compatible(expected, aty):
                raise SemanticError(_diag(filename, arg.line, arg.col, f"arg {i} for gpu.launch kernel expects {expected}, got {aty}"))
        setattr(e, "launch_resolved_name", chosen.symbol or chosen.name)
        return "Void"

    kernel_ty = _canonical_type(arg_types[0])
    parsed = _parse_fn_type(kernel_ty)
    if parsed is None:
        raise SemanticError(_diag(filename, kernel_expr.line, kernel_expr.col, "gpu.launch arg 0 must be a gpu kernel function"))
    param_tys, ret_ty, _ = parsed
    if _canonical_type(ret_ty) != "Void":
        raise SemanticError(_diag(filename, kernel_expr.line, kernel_expr.col, "gpu.launch kernel function must return Void"))
    if len(param_tys) != len(launch_arg_types):
        raise SemanticError(_diag(filename, e.line, e.col, f"gpu.launch kernel expects {len(param_tys)} args, got {len(launch_arg_types)}"))
    for i, (expected, arg, aty) in enumerate(zip(param_tys, launch_args, launch_arg_types), start=3):
        if not _gpu_launch_arg_compatible(expected, aty):
            raise SemanticError(_diag(filename, arg.line, arg.col, f"arg {i} for gpu.launch kernel expects {expected}, got {aty}"))
    return "Void"


def _infer_call(
    e: Call,
    scopes: list[dict[str, str]],
    mut_scopes: list[dict[str, bool]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    owned: _OwnedState | None,
    borrow: _BorrowState,
    move: _MoveState,
    filename: str,
    fn_name: str,
    unsafe_ok: bool,
    gpu_kernel: bool,
) -> str:
    spawn_like = False
    gpu_launch_like = False
    if isinstance(e.fn, Name):
        base = e.fn.value[2:] if e.fn.value.startswith("__") else e.fn.value
        spawn_like = base == "spawn"
    if (
        isinstance(e.fn, FieldExpr)
        and isinstance(e.fn.obj, Name)
        and e.fn.obj.value == "gpu"
        and _lookup("gpu", scopes) is None
        and e.fn.field == "launch"
    ):
        gpu_launch_like = True
    arg_types: list[str] = []
    for i, arg in enumerate(e.args):
        if (spawn_like or gpu_launch_like) and i == 0 and isinstance(arg, Name) and arg.value in fn_groups and len(fn_groups[arg.value]) > 1:
            arg_types.append("Any")
            continue
        arg_types.append(_infer(arg, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel))
    _check_call_arg_borrows(e.args, mut_scopes, borrow, filename)

    def _require_unsafe_context(callee_name: str, line: int, col: int) -> None:
        if unsafe_ok:
            return
        raise SemanticError(_diag(filename, line, col, f"call to unsafe function {callee_name} requires unsafe context"))

    if (
        isinstance(e.fn, FieldExpr)
        and isinstance(e.fn.obj, Name)
        and e.fn.obj.value == "gpu"
        and _lookup("gpu", scopes) is None
    ):
        return _infer_gpu_namespace_call(e, e.fn.field, arg_types, fn_groups, structs, enums, filename, gpu_kernel)

    if isinstance(e.fn, Name):
        name = e.fn.value
        builtin_base = name[2:] if name.startswith("__") else name
        if gpu_kernel and builtin_base in BUILTIN_SIGS and builtin_base not in GPU_ALLOWED_IN_KERNEL_BUILTINS:
            raise SemanticError(_diag(filename, e.line, e.col, f"builtin {builtin_base} is not available in gpu kernels"))
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
                    _consume_if_move_name(arg, aty, borrow, move, filename, arg.line, arg.col)
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
            return f"{_vec_inner(src_ty)}?"
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
            if not gpu_kernel:
                gpu_decls = [d for d in fn_groups[name] if isinstance(d, FnDecl) and bool(getattr(d, "gpu_kernel", False))]
                host_decls = [d for d in fn_groups[name] if not (isinstance(d, FnDecl) and bool(getattr(d, "gpu_kernel", False)))]
                if gpu_decls and not host_decls:
                    raise SemanticError(_diag(filename, e.line, e.col, f"gpu kernel {name} cannot be called directly; use gpu.launch"))
            decl = _choose_impl(name, fn_groups[name], arg_types, known_types, filename, e.line, e.col)
            if isinstance(decl, FnDecl) and bool(getattr(decl, "gpu_kernel", False)):
                if not gpu_kernel:
                    raise SemanticError(_diag(filename, e.line, e.col, f"gpu kernel {name} cannot be called directly; use gpu.launch"))
            elif gpu_kernel:
                raise SemanticError(_diag(filename, e.line, e.col, f"gpu kernels cannot call host function {name}"))
            if getattr(decl, "unsafe", False):
                _require_unsafe_context(name, e.line, e.col)
            is_variadic = bool(getattr(decl, "is_variadic", False))
            if is_variadic:
                if len(e.args) < len(decl.params):
                    raise SemanticError(
                        _diag(filename, e.line, e.col, f"{name} expects at least {len(decl.params)} args, got {len(e.args)}")
                    )
            elif len(e.args) != len(decl.params):
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects {len(decl.params)} args, got {len(e.args)}"))
            type_bindings: dict[str, str] = {}
            for i, ((_, pty), arg) in enumerate(zip(decl.params, e.args)):
                aty = arg_types[i]
                if _is_typevar(pty, known_types):
                    bound = type_bindings.get(pty)
                    if bound is None:
                        type_bindings[pty] = aty
                    elif not _same_type(bound, aty):
                        raise SemanticError(_diag(filename, arg.line, arg.col, f"inconsistent generic binding for {pty}: {bound} vs {aty}"))
                if not _is_typevar(pty, known_types):
                    _require_type(filename, arg.line, arg.col, pty, aty, f"arg {i} for {name}")
                if not _is_ref_type(pty) and pty != "Any" and not _is_typevar(pty, known_types):
                    _consume_if_move_name(arg, aty, borrow, move, filename, arg.line, arg.col)
            if isinstance(decl, FnDecl):
                e.resolved_name = decl.symbol or decl.name
            return _substitute_typevars(decl.ret, type_bindings)
        local = _lookup(name, scopes)
        if local is not None:
            if gpu_kernel:
                raise SemanticError(_diag(filename, e.line, e.col, "function-pointer calls are not supported in gpu kernels"))
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
                    _consume_if_move_name(arg, aty, borrow, move, filename, arg.line, arg.col)
            return ret_ty
        if name in structs:
            fields = structs[name].fields
            if len(e.args) != len(fields):
                raise SemanticError(_diag(filename, e.line, e.col, f"struct {name} expects {len(fields)} fields, got {len(e.args)}"))
            for i, ((_, fty), arg) in enumerate(zip(fields, e.args)):
                aty = arg_types[i]
                _require_type(filename, arg.line, arg.col, fty, aty, f"struct field for {name}")
                _consume_if_move_name(arg, aty, borrow, move, filename, arg.line, arg.col)
            return name
        sig = BUILTIN_SIGS.get(name)
        if sig is not None:
            base = _builtin_base_name(name)
            if gpu_kernel and base not in GPU_ALLOWED_IN_KERNEL_BUILTINS:
                raise SemanticError(_diag(filename, e.line, e.col, f"builtin {base} is not available in gpu kernels"))
            _require_freestanding_builtin_allowed(name, filename, e.line, e.col)
            if base == "to_json":
                if len(e.args) != 1:
                    raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects 1 args, got {len(e.args)}"))
                return "String"
            if sig.args is not None and len(e.args) != len(sig.args):
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects {len(sig.args)} args, got {len(e.args)}"))
            if sig.args is not None:
                for i, (expected, arg) in enumerate(zip(sig.args, e.args)):
                    aty = arg_types[i]
                    _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for {name}")
            return sig.ret
        raise SemanticError(_diag(filename, e.line, e.col, f"undefined function {name}"))
    if isinstance(e.fn, FieldExpr):
        if isinstance(e.fn.obj, Name) and _lookup(e.fn.obj.value, scopes) is None and e.fn.obj.value in enums:
            enum_decl = enums[e.fn.obj.value]
            variant = None
            for vname, vtypes in enum_decl.variants:
                if vname == e.fn.field:
                    variant = (vname, vtypes)
                    break
            if variant is None:
                raise SemanticError(
                    _diag(filename, e.line, e.col, f"unknown enum variant {enum_decl.name}.{e.fn.field}")
                )
            _, payload_types = variant
            if len(e.args) != len(payload_types):
                raise SemanticError(
                    _diag(
                        filename,
                        e.line,
                        e.col,
                        f"{enum_decl.name}.{e.fn.field} expects {len(payload_types)} args, got {len(e.args)}",
                    )
                )
            type_bindings: dict[str, str] = {}
            type_param_set = set(enum_decl.generics)
            fn_ret_defaults: dict[str, str] = {}
            fn_ret = _canonical_type(getattr(move, "fn_ret", ""))
            fn_ret_param = _parse_parametric_type(fn_ret)
            if fn_ret_param is not None:
                fn_base, fn_args = fn_ret_param
                if fn_base == enum_decl.name and len(fn_args) == len(enum_decl.generics):
                    fn_ret_defaults = {tp: ty for tp, ty in zip(enum_decl.generics, fn_args)}
            for i, (expected, arg) in enumerate(zip(payload_types, e.args)):
                aty = arg_types[i]
                exp_c = _canonical_type(expected)
                if exp_c in type_param_set:
                    prev = type_bindings.get(exp_c)
                    if prev is None:
                        type_bindings[exp_c] = aty
                    else:
                        _require_type(filename, arg.line, arg.col, prev, aty, f"arg {i} for {enum_decl.name}.{e.fn.field}")
                else:
                    _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for {enum_decl.name}.{e.fn.field}")
                if not _is_ref_type(aty):
                    _consume_if_move_name(arg, aty, borrow, move, filename, arg.line, arg.col)
            if enum_decl.generics:
                bound = [type_bindings.get(tp, fn_ret_defaults.get(tp, "Any")) for tp in enum_decl.generics]
                return f"{enum_decl.name}<{', '.join(bound)}>"
            return enum_decl.name
        obj_ty = _infer(e.fn.obj, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
        if e.fn.field in fn_groups:
            ufcs_name = e.fn.field
            all_arg_types = [obj_ty] + arg_types
            known_types = set(PRIMITIVES) | set(structs.keys()) | set(enums.keys())
            decl = _choose_impl(ufcs_name, fn_groups[ufcs_name], all_arg_types, known_types, filename, e.line, e.col)
            if isinstance(decl, FnDecl) and bool(getattr(decl, "gpu_kernel", False)):
                if not gpu_kernel:
                    raise SemanticError(_diag(filename, e.line, e.col, f"gpu kernel {ufcs_name} cannot be called directly; use gpu.launch"))
            elif gpu_kernel:
                raise SemanticError(_diag(filename, e.line, e.col, f"gpu kernels cannot call host function {ufcs_name}"))
            if getattr(decl, "unsafe", False):
                _require_unsafe_context(ufcs_name, e.line, e.col)
            if len(decl.params) != len(all_arg_types):
                raise SemanticError(_diag(filename, e.line, e.col, f"{ufcs_name} expects {len(decl.params)} args, got {len(all_arg_types)}"))
            type_bindings: dict[str, str] = {}
            receiver_and_args = [e.fn.obj] + e.args
            for i, ((_, pty), arg, aty) in enumerate(zip(decl.params, receiver_and_args, all_arg_types)):
                if _is_typevar(pty, known_types):
                    bound = type_bindings.get(pty)
                    if bound is None:
                        type_bindings[pty] = aty
                    elif not _same_type(bound, aty):
                        raise SemanticError(_diag(filename, arg.line, arg.col, f"inconsistent generic binding for {pty}: {bound} vs {aty}"))
                    continue
                if i == 0 and _is_ref_type(pty):
                    inner = _strip_ref(pty)
                    _require_type(filename, arg.line, arg.col, inner, aty, f"receiver for {ufcs_name}")
                    if pty.startswith("&mut "):
                        if not isinstance(arg, Name):
                            raise SemanticError(_diag(filename, arg.line, arg.col, f"mutable receiver for {ufcs_name} must be a name"))
                        is_mutable = _lookup_mut(arg.value, mut_scopes)
                        if not is_mutable:
                            raise SemanticError(_diag(filename, arg.line, arg.col, f"receiver {arg.value} must be mutable for {ufcs_name}"))
                    continue
                _require_type(filename, arg.line, arg.col, pty, aty, f"arg {i} for {ufcs_name}")
                if not _is_ref_type(pty) and pty != "Any" and not _is_typevar(pty, known_types):
                    _consume_if_move_name(arg, aty, borrow, move, filename, arg.line, arg.col)
            if isinstance(decl, FnDecl):
                e.resolved_name = decl.symbol or decl.name
            setattr(e, "ufcs_receiver", e.fn.obj)
            setattr(e, "ufcs_receiver_ty", obj_ty)
            return _substitute_typevars(decl.ret, type_bindings)
        if e.fn.field == "get":
            if len(e.args) != 1:
                raise SemanticError(_diag(filename, e.line, e.col, "get expects 1 arg"))
            _require_type(filename, e.args[0].line, e.args[0].col, "Int", arg_types[0], "arg 0 for get")
            base_ty = _strip_ref(_canonical_type(obj_ty))
            if _is_slice_type(base_ty):
                return f"{_slice_inner(base_ty)}?"
            if _is_vec_type(base_ty):
                return f"{_vec_inner(base_ty)}?"
        if e.fn.field == "len":
            if len(e.args) != 0:
                raise SemanticError(_diag(filename, e.line, e.col, "len expects 0 args"))
            base_ty = _strip_ref(_canonical_type(obj_ty))
            if _is_vec_type(base_ty) or _is_slice_type(base_ty) or _is_gpu_memory_type(base_ty):
                return "Int"
        return "Any"
    callee_ty = _infer(e.fn, scopes, mut_scopes, fn_groups, structs, enums, owned, borrow, move, filename, fn_name, unsafe_ok, gpu_kernel)
    if gpu_kernel:
        raise SemanticError(_diag(filename, e.line, e.col, "function-pointer calls are not supported in gpu kernels"))
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
            _consume_if_move_name(arg, aty, borrow, move, filename, arg.line, arg.col)
    return ret_ty


def _is_alloc_call(expr):
    return isinstance(expr, Call) and isinstance(expr.fn, Name) and expr.fn.value == "alloc"


def _is_free_call(expr):
    return isinstance(expr, Call) and isinstance(expr.fn, Name) and expr.fn.value == "free" and len(expr.args) == 1
