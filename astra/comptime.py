"""Compile-time evaluator for `comptime` blocks and constant execution."""
from __future__ import annotations

import copy
from dataclasses import dataclass
import math

from astra.ast import *
from astra.int_types import is_int_type_name, parse_int_type_name
from astra.layout import LayoutError, canonical_type, layout_of_type


class ComptimeError(Exception):
    """Error type raised by the comptime subsystem.

    This type is part of Astra's public compiler/tooling surface.
    """

    def __init__(self, message: str, *, span: tuple[str, int, int] | None = None):
        super().__init__(message)
        self.span = span


def _diag(filename: str, line: int, col: int, msg: str) -> str:
    return f"SEM {filename}:{line}:{col}: comptime: {msg}"


def _diag_with_span(filename: str, line: int, col: int, msg: str) -> tuple[str, tuple[str, int, int]]:
    """Return (message, span) for richer error construction."""
    return f"SEM {filename}:{line}:{col}: comptime: {msg}", (filename, line, col)


def _ast_of(v, node) -> Any:
    if v is None:
        return NilLit(pos=getattr(node, "pos", 0), line=getattr(node, "line", 0), col=getattr(node, "col", 0))
    if isinstance(v, bool):
        return BoolLit(v, pos=getattr(node, "pos", 0), line=getattr(node, "line", 0), col=getattr(node, "col", 0))
    if isinstance(v, (int, float, str)):
        return Literal(v, pos=getattr(node, "pos", 0), line=getattr(node, "line", 0), col=getattr(node, "col", 0))
    if isinstance(v, list):
        return ArrayLit([_ast_of(x, node) for x in v], pos=getattr(node, "pos", 0), line=getattr(node, "line", 0), col=getattr(node, "col", 0))
    raise ComptimeError(_diag("<input>", getattr(node, "line", 0), getattr(node, "col", 0), f"unsupported comptime value type {type(v).__name__}"))


@dataclass
class _LoopSignal:
    kind: str
    value: object = None


@dataclass(frozen=True)
class _FnRef:
    name: str


class _Evaluator:
    def __init__(self, fn_map: dict[str, FnDecl], structs: dict[str, StructDecl], filename: str, overflow_mode: str = "trap"):
        self.fn_map = fn_map
        self.structs = structs
        self.filename = filename
        self.overflow_mode = overflow_mode
        self.max_steps = 100_000
        self.steps = 0
        self.heap: dict[int, bytearray] = {}
        self.next_ptr = 1
        self.banned = {
            "print",
            "read_file",
            "write_file",
            "args",
            "arg",
            "spawn",
            "join",
            "tcp_connect",
            "tcp_send",
            "tcp_recv",
            "tcp_close",
            "tcp_connect_timeout",
            "tcp_set_nonblocking",
            "tcp_recv_timeout",
            "tcp_listen",
            "tcp_accept",
            "proc_run",
            "proc_exit",
            "env_get",
            "cwd",
            "now_unix",
            "monotonic_ms",
            "sleep_ms",
            "sleep_until",
            "join_timeout",
            "chan_send_timeout",
            "chan_recv_timeout",
            "mutex_try_lock",
            "hkdf_sha256",
            "aead_encrypt",
            "aead_decrypt",
            "__now_unix",
            "__monotonic_ms",
            "__sleep_ms",
            "__sleep_until",
            "__join_timeout",
            "__tcp_connect_timeout",
            "__tcp_set_nonblocking",
            "__tcp_recv_timeout",
            "__tcp_listen",
            "__tcp_accept",
            "__chan_send_timeout",
            "__chan_recv_timeout",
            "__mutex_try_lock",
            "__hkdf_sha256",
            "__aead_encrypt",
            "__aead_decrypt",
        }

    def _tick(self, node):
        self.steps += 1
        if self.steps > self.max_steps:
            raise ComptimeError(_diag(self.filename, getattr(node, "line", 0), getattr(node, "col", 0), "step limit exceeded"))

    def _fn_type(self, fn: FnDecl) -> str:
        return f"fn({', '.join(t for _, t in fn.params)}) -> {fn.ret}"

    def _value_type(self, value: object) -> str:
        if isinstance(value, _FnRef):
            fn = self.fn_map.get(value.name)
            if fn is not None:
                return self._fn_type(fn)
            return "fn(...) -> Any"
        inferred = _value_type_name(value)
        if inferred is not None:
            return inferred
        return type(value).__name__

    def _call_target_name(self, callee: Any, env: dict[str, object], env_types: dict[str, str], node: Any) -> str:
        if isinstance(callee, Name):
            if callee.value in env:
                val = env[callee.value]
                if isinstance(val, _FnRef):
                    return val.name
                ty = canonical_type(env_types.get(callee.value, self._value_type(val)))
                raise ComptimeError(_diag(self.filename, node.line, node.col, f"cannot call value of non-function type {ty}"))
            return callee.value
        val = self.eval_expr(callee, env, env_types)
        if isinstance(val, _FnRef):
            return val.name
        raise ComptimeError(_diag(self.filename, node.line, node.col, f"cannot call value of non-function type {self._value_type(val)}"))

    def _dispatch_call(self, name: str, args: list[object], arg_nodes: list[Any], env: dict[str, object], env_types: dict[str, str], node: Any):
        if name in self.banned:
            raise ComptimeError(_diag(self.filename, node.line, node.col, f"call to non-pure function {name}"))
        if name == "len":
            if len(args) != 1:
                raise ComptimeError(_diag(self.filename, node.line, node.col, "len expects 1 argument"))
            return len(args[0])
        if name in {
            "countOnes",
            "__countOnes",
            "leadingZeros",
            "__leadingZeros",
            "trailingZeros",
            "__trailingZeros",
            "popcnt",
            "__popcnt",
            "clz",
            "__clz",
            "ctz",
            "__ctz",
        }:
            if len(args) != 1:
                raise ComptimeError(_diag(self.filename, node.line, node.col, f"{name} expects 1 argument"))
            ty = self._expr_type_hint(arg_nodes[0], env, env_types) or "Int"
            if not _is_int_type_name(ty):
                raise ComptimeError(_diag(self.filename, node.line, node.col, f"{name} expects integer argument, got {ty}"))
            bits, _ = _int_props(ty)
            v = int(args[0]) & ((1 << bits) - 1)
            base = name[2:] if name.startswith("__") else name
            if base in {"countOnes", "popcnt"}:
                return v.bit_count()
            if base in {"leadingZeros", "clz"}:
                return bits if v == 0 else max(0, bits - v.bit_length())
            if v == 0:
                return bits
            c = 0
            while (v & 1) == 0:
                v >>= 1
                c += 1
            return c
        if name in {"rotl", "__rotl", "rotr", "__rotr"}:
            if len(args) != 2:
                raise ComptimeError(_diag(self.filename, node.line, node.col, f"{name} expects 2 arguments"))
            ty = self._expr_type_hint(arg_nodes[0], env, env_types) or "Int"
            if not _is_int_type_name(ty):
                raise ComptimeError(_diag(self.filename, node.line, node.col, f"{name} expects integer arg 0, got {ty}"))
            rhs_ty = self._expr_type_hint(arg_nodes[1], env, env_types) or "Int"
            if not _is_int_type_name(rhs_ty):
                raise ComptimeError(_diag(self.filename, node.line, node.col, f"{name} expects integer arg 1, got {rhs_ty}"))
            bits, signed = _int_props(ty)
            mask = (1 << bits) - 1
            x = int(args[0]) & mask
            n = int(args[1]) % bits
            base = name[2:] if name.startswith("__") else name
            if base == "rotl":
                out = ((x << n) | (x >> ((bits - n) % bits))) & mask
            else:
                out = ((x >> n) | (x << ((bits - n) % bits))) & mask
            if signed and out >= (1 << (bits - 1)):
                out -= (1 << bits)
            return out
        if name == "alloc":
            if len(args) != 1:
                raise ComptimeError(_diag(self.filename, node.line, node.col, "alloc expects 1 argument"))
            ptr = self.next_ptr
            self.next_ptr += 1
            self.heap[ptr] = bytearray(max(0, int(args[0])))
            return ptr
        if name == "free":
            if len(args) != 1:
                raise ComptimeError(_diag(self.filename, node.line, node.col, "free expects 1 argument"))
            self.heap.pop(int(args[0]), None)
            return 0
        fn = self.fn_map.get(name)
        if fn is not None:
            arg_types = [self._expr_type_hint(a, env, env_types) for a in arg_nodes]
            return self.call_user_fn(fn, args, arg_types=arg_types, depth=0)
        raise ComptimeError(_diag(self.filename, node.line, node.col, f"undefined function {name}"))

    def eval_expr(self, e, env, env_types: dict[str, str] | None = None):
        if env_types is None:
            env_types = {}
        self._tick(e)
        if isinstance(e, Literal):
            return e.value
        if isinstance(e, BoolLit):
            return e.value
        if isinstance(e, NilLit):
            return None
        if isinstance(e, SizeOfTypeExpr):
            return layout_of_type(e.type_name, self.structs, mode="query").size
        if isinstance(e, AlignOfTypeExpr):
            return layout_of_type(e.type_name, self.structs, mode="query").align
        if isinstance(e, BitSizeOfTypeExpr):
            return layout_of_type(e.type_name, self.structs, mode="query").bits
        if isinstance(e, MaxValTypeExpr):
            ty = canonical_type(e.type_name)
            if not is_int_type_name(ty):
                raise ComptimeError(_diag(self.filename, e.line, e.col, f"maxVal expects integer type, got {ty}"))
            bits, signed = _int_props(ty)
            return _int_max(bits, signed)
        if isinstance(e, MinValTypeExpr):
            ty = canonical_type(e.type_name)
            if not is_int_type_name(ty):
                raise ComptimeError(_diag(self.filename, e.line, e.col, f"minVal expects integer type, got {ty}"))
            bits, signed = _int_props(ty)
            return _int_min(bits) if signed else 0
        if isinstance(e, SizeOfValueExpr):
            return self._layout_for_value_expr(e.expr, env, env_types).size
        if isinstance(e, AlignOfValueExpr):
            return self._layout_for_value_expr(e.expr, env, env_types).align
        if isinstance(e, Name):
            if e.value in env:
                return env[e.value]
            if e.value in self.fn_map:
                return _FnRef(e.value)
            raise ComptimeError(_diag(self.filename, e.line, e.col, f"undefined name {e.value}"))
        if isinstance(e, ArrayLit):
            return [self.eval_expr(x, env, env_types) for x in e.elements]
        if isinstance(e, CastExpr):
            return self._eval_cast(self.eval_expr(e.expr, env, env_types), e.type_name, e)
        if isinstance(e, Unary):
            v = self.eval_expr(e.expr, env, env_types)
            if e.op == "-":
                if _is_plain_int(v):
                    return self._apply_int_overflow(-int(v), self._int_type_hint(e, env, env_types), e)
                return -v
            if e.op == "!":
                return not bool(v)
            if e.op == "~":
                return self._apply_int_overflow(~int(v), self._int_type_hint(e, env, env_types), e)
            raise ComptimeError(_diag(self.filename, e.line, e.col, f"unsupported unary op {e.op}"))
        if isinstance(e, Binary):
            l = self.eval_expr(e.left, env, env_types)
            if e.op == "??":
                return l if l is not None else self.eval_expr(e.right, env, env_types)
            r = self.eval_expr(e.right, env, env_types)
            return self._eval_binary_values(e.op, l, r, self._int_type_hint(e, env, env_types), e)
        if isinstance(e, IndexExpr):
            o = self.eval_expr(e.obj, env, env_types)
            i = int(self.eval_expr(e.index, env, env_types))
            return o[i]
        if isinstance(e, FieldExpr):
            o = self.eval_expr(e.obj, env, env_types)
            if isinstance(o, dict):
                return o.get(e.field)
            raise ComptimeError(_diag(self.filename, e.line, e.col, "field access only supported for map-like values"))
        if isinstance(e, AwaitExpr):
            return self.eval_expr(e.expr, env, env_types)
        if isinstance(e, TryExpr):
            raise ComptimeError(_diag(self.filename, e.line, e.col, "`!` is not supported in comptime expressions"))
        if isinstance(e, Call):
            args = [self.eval_expr(a, env, env_types) for a in e.args]
            name = self._call_target_name(e.fn, env, env_types, e)
            return self._dispatch_call(name, args, e.args, env, env_types, e)
        raise ComptimeError(_diag(self.filename, getattr(e, "line", 0), getattr(e, "col", 0), f"unsupported expression {type(e).__name__}"))

    def _layout_for_value_expr(self, expr: Any, env: dict[str, object], env_types: dict[str, str]):
        ty = self._static_expr_type(expr, env, env_types)
        if ty is None:
            raise ComptimeError(_diag(self.filename, getattr(expr, "line", 0), getattr(expr, "col", 0), "unable to infer type for size_of/align_of"))
        try:
            return layout_of_type(ty, self.structs, mode="query")
        except LayoutError as err:
            raise ComptimeError(_diag(self.filename, getattr(expr, "line", 0), getattr(expr, "col", 0), str(err))) from err

    def _static_expr_type(self, expr: Any, env: dict[str, object], env_types: dict[str, str]) -> str | None:
        hinted = self._expr_type_hint(expr, env, env_types)
        if hinted is not None:
            return hinted
        return None

    def _expr_type_hint(self, expr: Any, env: dict[str, object], env_types: dict[str, str]) -> str | None:
        inferred = getattr(expr, "inferred_type", None)
        if isinstance(inferred, str):
            return canonical_type(inferred)
        if isinstance(expr, BoolLit):
            return "Bool"
        if isinstance(expr, NilLit):
            return None
        if isinstance(expr, Literal):
            if isinstance(expr.value, bool):
                return "Bool"
            if isinstance(expr.value, int):
                return "Int"
            if isinstance(expr.value, float):
                return "Float"
            return "String"
        if isinstance(expr, Name):
            if expr.value in env_types:
                return canonical_type(env_types[expr.value])
            val = env.get(expr.value)
            if isinstance(val, _FnRef):
                fn = self.fn_map.get(val.name)
                if fn is not None:
                    return canonical_type(self._fn_type(fn))
            if isinstance(val, bool):
                return "Bool"
            if isinstance(val, int):
                return "Int"
            if isinstance(val, float):
                return "Float"
            return None
        if isinstance(expr, CastExpr):
            return canonical_type(expr.type_name)
        if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr, BitSizeOfTypeExpr, SizeOfValueExpr, AlignOfValueExpr)):
            return "Int"
        if isinstance(expr, (MaxValTypeExpr, MinValTypeExpr)):
            return canonical_type(expr.type_name)
        if isinstance(expr, Unary):
            if expr.op == "!":
                return "Bool"
            return self._expr_type_hint(expr.expr, env, env_types)
        if isinstance(expr, Binary):
            if expr.op in {"==", "!=", "<", "<=", ">", ">=", "&&", "||"}:
                return "Bool"
            if expr.op == "??":
                return self._expr_type_hint(expr.right, env, env_types)
            if expr.op in {"+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>"}:
                return self._expr_type_hint(expr.left, env, env_types)
        return None

    def _int_type_hint(self, expr: Any, env: dict[str, object], env_types: dict[str, str]) -> str | None:
        ty = self._expr_type_hint(expr, env, env_types)
        if ty is None:
            return None
        c = canonical_type(ty)
        return c if _is_int_type_name(c) else None

    def _coerce_int_operand(self, value: int, int_ty: str, node: Any) -> int:
        bits, signed = _int_props(int_ty)
        if self.overflow_mode == "wrap":
            return _truncate_int(value, bits, signed)
        lo = _int_min(bits) if signed else 0
        hi = _int_max(bits, signed)
        if value < lo or value > hi:
            raise ComptimeError(_diag(self.filename, node.line, node.col, f"integer overflow for {int_ty} in comptime"))
        return value

    def _apply_int_overflow(self, value: int, int_ty: str | None, node: Any) -> int:
        if int_ty is None:
            return value
        return self._coerce_int_operand(int(value), int_ty, node)

    def _eval_binary_values(self, op: str, l: object, r: object, int_ty: str | None, node: Any) -> object:
        if op == "&&":
            return bool(l) and bool(r)
        if op == "||":
            return bool(l) or bool(r)
        if op in {"==", "!="}:
            return (l == r) if op == "==" else (l != r)
        if _is_plain_int(l) and _is_plain_int(r):
            ty = int_ty or "Int"
            bits, signed = _int_props(ty)
            lv = self._coerce_int_operand(int(l), ty, node)
            rv = self._coerce_int_operand(int(r), ty, node)
            if op == "+":
                return self._apply_int_overflow(lv + rv, ty, node)
            if op == "-":
                return self._apply_int_overflow(lv - rv, ty, node)
            if op == "*":
                return self._apply_int_overflow(lv * rv, ty, node)
            if op == "/":
                if rv == 0:
                    raise ComptimeError(_diag(self.filename, node.line, node.col, "division by zero"))
                q = _div_trunc_toward_zero(lv, rv)
                return self._apply_int_overflow(q, ty, node)
            if op == "%":
                if rv == 0:
                    raise ComptimeError(_diag(self.filename, node.line, node.col, "modulo by zero"))
                q = _div_trunc_toward_zero(lv, rv)
                m = lv - (q * rv)
                return self._apply_int_overflow(m, ty, node)
            if op == "&":
                return self._apply_int_overflow(lv & rv, ty, node)
            if op == "|":
                return self._apply_int_overflow(lv | rv, ty, node)
            if op == "^":
                return self._apply_int_overflow(lv ^ rv, ty, node)
            if op == "<<":
                if rv < 0:
                    raise ComptimeError(_diag(self.filename, node.line, node.col, "negative shift count"))
                return self._apply_int_overflow(lv << rv, ty, node)
            if op == ">>":
                if rv < 0:
                    raise ComptimeError(_diag(self.filename, node.line, node.col, "negative shift count"))
                if not signed:
                    mask = (1 << bits) - 1
                    val = lv & mask
                    out = 0 if rv >= bits else (val >> rv)
                    return self._apply_int_overflow(out, ty, node)
                return self._apply_int_overflow(lv >> rv, ty, node)
            if op in {"<", "<=", ">", ">="}:
                if not signed:
                    mask = (1 << bits) - 1
                    lv_cmp = lv & mask
                    rv_cmp = rv & mask
                else:
                    lv_cmp = lv
                    rv_cmp = rv
                if op == "<":
                    return lv_cmp < rv_cmp
                if op == "<=":
                    return lv_cmp <= rv_cmp
                if op == ">":
                    return lv_cmp > rv_cmp
                return lv_cmp >= rv_cmp
        if op == "+":
            return l + r
        if op == "-":
            return l - r
        if op == "*":
            return l * r
        if op == "/":
            return l / r
        if op == "%":
            return l % r
        if op == "<":
            return l < r
        if op == "<=":
            return l <= r
        if op == ">":
            return l > r
        if op == ">=":
            return l >= r
        raise ComptimeError(_diag(self.filename, node.line, node.col, f"unsupported binary op {op}"))

    def _eval_cast(self, value: object, target_type: str, node: Any) -> object:
        ty = canonical_type(target_type)
        if ty in {"Float", "f64", "f32"}:
            if isinstance(value, bool):
                return float(int(value))
            if isinstance(value, (int, float)):
                return float(value)
            raise ComptimeError(_diag(self.filename, node.line, node.col, f"cannot cast to {target_type}"))
        if is_int_type_name(ty):
            return self._cast_to_int(value, ty, node)
        raise ComptimeError(_diag(self.filename, node.line, node.col, f"unsupported cast target {target_type}"))

    def _cast_to_int(self, value: object, ty: str, node: Any) -> int:
        bits, signed = _int_props(ty)
        if isinstance(value, bool):
            iv = int(value)
        elif isinstance(value, int):
            iv = value
        elif isinstance(value, float):
            if math.isnan(value):
                return 0
            if math.isinf(value):
                if value > 0:
                    return _int_max(bits, signed)
                if signed:
                    return _int_min(bits)
                return 0
            iv = math.trunc(value)
        else:
            raise ComptimeError(_diag(self.filename, node.line, node.col, f"cannot cast to {ty}"))
        
        # Add range validation for comptime evaluation
        min_val = _int_min(bits) if signed else 0
        max_val = _int_max(bits, signed)
        if iv < min_val or iv > max_val:
            raise ComptimeError(_diag(self.filename, node.line, node.col,
                f"comptime result {iv} out of range for {ty} (expected {min_val}..{max_val})"))
        
        return _truncate_int(iv, bits, signed)

    def _match_pattern(self, pat: Any, subj: object, env: dict[str, object], env_types: dict[str, str]) -> bool:
        if isinstance(pat, WildcardPattern):
            return True
        if isinstance(pat, OrPattern):
            return any(self._match_pattern(p, subj, env, env_types) for p in pat.patterns)
        if isinstance(pat, GuardedPattern):
            return self._match_pattern(pat.pattern, subj, env, env_types) and bool(self.eval_expr(pat.guard, env, env_types))
        return subj == self.eval_expr(pat, env, env_types)

    def exec_stmt(self, st, env, env_types: dict[str, str]):
        self._tick(st)
        if isinstance(st, LetStmt):
            val = self.eval_expr(st.expr, env, env_types)
            env[st.name] = val
            if st.type_name is not None:
                env_types[st.name] = canonical_type(st.type_name)
            else:
                inferred = _value_type_name(val)
                if inferred is not None:
                    env_types[st.name] = inferred
            return None
        if isinstance(st, AssignStmt):
            if not isinstance(st.target, Name):
                raise ComptimeError(_diag(self.filename, st.line, st.col, "comptime assignment target must be a name"))
            rhs = self.eval_expr(st.expr, env, env_types)
            if st.op == "=":
                env[st.target.value] = rhs
                if st.target.value not in env_types:
                    inferred = _value_type_name(rhs)
                    if inferred is not None:
                        env_types[st.target.value] = inferred
            else:
                cur = env.get(st.target.value)
                if cur is None:
                    raise ComptimeError(_diag(self.filename, st.line, st.col, f"undefined name {st.target.value}"))
                int_ty = canonical_type(env_types.get(st.target.value, "Int"))
                env[st.target.value] = self._eval_binary_values(st.op[:-1], cur, rhs, int_ty, st)
            return None
        if isinstance(st, ExprStmt):
            self.eval_expr(st.expr, env, env_types)
            return None
        if isinstance(st, DropStmt):
            self.eval_expr(st.expr, env, env_types)
            return None
        if isinstance(st, ReturnStmt):
            v = None if st.expr is None else self.eval_expr(st.expr, env, env_types)
            return _LoopSignal("return", v)
        if isinstance(st, BreakStmt):
            return _LoopSignal("break")
        if isinstance(st, ContinueStmt):
            return _LoopSignal("continue")
        if isinstance(st, DeferStmt):
            return None
        if isinstance(st, IfStmt):
            branch = st.then_body if bool(self.eval_expr(st.cond, env, env_types)) else st.else_body
            for s in branch:
                sig = self.exec_stmt(s, env, env_types)
                if isinstance(sig, _LoopSignal):
                    return sig
            return None
        if isinstance(st, MatchStmt):
            subj = self.eval_expr(st.expr, env, env_types)
            for pat, body in st.arms:
                if not self._match_pattern(pat, subj, env, env_types):
                    continue
                for s in body:
                    sig = self.exec_stmt(s, env, env_types)
                    if isinstance(sig, _LoopSignal):
                        return sig
                return None
            return None
        if isinstance(st, WhileStmt):
            while bool(self.eval_expr(st.cond, env, env_types)):
                for s in st.body:
                    sig = self.exec_stmt(s, env, env_types)
                    if not isinstance(sig, _LoopSignal):
                        continue
                    if sig.kind == "continue":
                        break
                    if sig.kind == "break":
                        return None
                    return sig
            return None
        if isinstance(st, ForStmt):
            seq: list[object]
            if isinstance(st.iterable, RangeExpr):
                start = int(self.eval_expr(st.iterable.start, env, env_types))
                end = int(self.eval_expr(st.iterable.end, env, env_types))
                stop = end + 1 if st.iterable.inclusive else end
                seq = list(range(start, stop))
            else:
                seq = list(self.eval_expr(st.iterable, env, env_types))
            had_old = st.var in env
            old_v = env.get(st.var)
            old_ty = env_types.get(st.var)
            for it in seq:
                env[st.var] = it
                env_types[st.var] = self._value_type(it)
                for s in st.body:
                    sig = self.exec_stmt(s, env, env_types)
                    if not isinstance(sig, _LoopSignal):
                        continue
                    if sig.kind == "continue":
                        break
                    if sig.kind == "break":
                        if had_old:
                            env[st.var] = old_v
                            if old_ty is not None:
                                env_types[st.var] = old_ty
                            else:
                                env_types.pop(st.var, None)
                        else:
                            env.pop(st.var, None)
                            env_types.pop(st.var, None)
                        return None
                    return sig
            if had_old:
                env[st.var] = old_v
                if old_ty is not None:
                    env_types[st.var] = old_ty
                else:
                    env_types.pop(st.var, None)
            else:
                env.pop(st.var, None)
                env_types.pop(st.var, None)
            return None
        if isinstance(st, ComptimeStmt):
            for s in st.body:
                sig = self.exec_stmt(s, env, env_types)
                if isinstance(sig, _LoopSignal):
                    return sig
            return None
        if isinstance(st, UnsafeStmt):
            for s in st.body:
                sig = self.exec_stmt(s, env, env_types)
                if isinstance(sig, _LoopSignal):
                    return sig
            return None
        raise ComptimeError(_diag(self.filename, getattr(st, "line", 0), getattr(st, "col", 0), f"unsupported statement {type(st).__name__}"))

    def call_user_fn(self, fn: FnDecl, args: list[object], arg_types: list[str | None], depth: int):
        if depth > 64:
            raise ComptimeError(_diag(self.filename, fn.line, fn.col, "comptime recursion limit exceeded"))
        if fn.async_fn:
            raise ComptimeError(_diag(self.filename, fn.line, fn.col, "async fn cannot run in comptime"))
        if len(args) != len(fn.params):
            raise ComptimeError(_diag(self.filename, fn.line, fn.col, f"{fn.name} expects {len(fn.params)} args, got {len(args)}"))
        env = {name: value for (name, _), value in zip(fn.params, args)}
        env_types: dict[str, str] = {}
        for idx, (name, typ) in enumerate(fn.params):
            hinted = arg_types[idx] if idx < len(arg_types) else None
            env_types[name] = canonical_type(hinted or typ)
        for st in fn.body:
            sig = self.exec_stmt(st, env, env_types)
            if isinstance(sig, _LoopSignal) and sig.kind == "return":
                return sig.value
        return None


def _int_props(typ: str) -> tuple[int, bool]:
    parsed = parse_int_type_name(canonical_type(typ))
    if parsed is not None:
        bits, signed = parsed
        return bits, signed
    return 64, True


def _int_min(bits: int) -> int:
    return -(1 << (bits - 1))


def _int_max(bits: int, signed: bool) -> int:
    if signed:
        return (1 << (bits - 1)) - 1
    return (1 << bits) - 1


def _truncate_int(value: int, bits: int, signed: bool) -> int:
    mask = (1 << bits) - 1
    out = int(value) & mask
    if signed and bits > 0 and out >= (1 << (bits - 1)):
        out -= 1 << bits
    return out


def _is_int_type_name(typ: str | None) -> bool:
    if typ is None:
        return False
    return is_int_type_name(canonical_type(typ))


def _is_plain_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _value_type_name(value: object) -> str | None:
    if isinstance(value, bool):
        return "Bool"
    if _is_plain_int(value):
        return "Int"
    if isinstance(value, float):
        return "Float"
    if isinstance(value, str):
        return "&str"
    return None


def _div_trunc_toward_zero(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return -q if (a < 0) ^ (b < 0) else q


def _collect_runtime_name_uses_expr(expr: Any, out: set[str]) -> None:
    if isinstance(expr, Name):
        out.add(expr.value)
        return
    if isinstance(expr, Unary):
        _collect_runtime_name_uses_expr(expr.expr, out)
        return
    if isinstance(expr, Binary):
        _collect_runtime_name_uses_expr(expr.left, out)
        _collect_runtime_name_uses_expr(expr.right, out)
        return
    if isinstance(expr, CastExpr):
        _collect_runtime_name_uses_expr(expr.expr, out)
        return
    if isinstance(expr, AwaitExpr):
        _collect_runtime_name_uses_expr(expr.expr, out)
        return
    if isinstance(expr, TryExpr):
        _collect_runtime_name_uses_expr(expr.expr, out)
        return
    if isinstance(expr, Call):
        _collect_runtime_name_uses_expr(expr.fn, out)
        for a in expr.args:
            _collect_runtime_name_uses_expr(a, out)
        return
    if isinstance(expr, IndexExpr):
        _collect_runtime_name_uses_expr(expr.obj, out)
        _collect_runtime_name_uses_expr(expr.index, out)
        return
    if isinstance(expr, FieldExpr):
        _collect_runtime_name_uses_expr(expr.obj, out)
        return
    if isinstance(expr, OrPattern):
        for p in expr.patterns:
            _collect_runtime_name_uses_expr(p, out)
        return
    if isinstance(expr, GuardedPattern):
        _collect_runtime_name_uses_expr(expr.pattern, out)
        _collect_runtime_name_uses_expr(expr.guard, out)
        return
    if isinstance(expr, ArrayLit):
        for e in expr.elements:
            _collect_runtime_name_uses_expr(e, out)
        return
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        _collect_runtime_name_uses_expr(expr.expr, out)
        return


def _collect_runtime_name_uses_stmt(stmt: Any, out: set[str]) -> None:
    if isinstance(stmt, LetStmt):
        _collect_runtime_name_uses_expr(stmt.expr, out)
        return
    if isinstance(stmt, AssignStmt):
        _collect_runtime_name_uses_expr(stmt.target, out)
        _collect_runtime_name_uses_expr(stmt.expr, out)
        return
    if isinstance(stmt, ReturnStmt):
        if stmt.expr is not None:
            _collect_runtime_name_uses_expr(stmt.expr, out)
        return
    if isinstance(stmt, ExprStmt):
        _collect_runtime_name_uses_expr(stmt.expr, out)
        return
    if isinstance(stmt, DropStmt):
        _collect_runtime_name_uses_expr(stmt.expr, out)
        return
    if isinstance(stmt, DeferStmt):
        _collect_runtime_name_uses_expr(stmt.expr, out)
        return
    if isinstance(stmt, IfStmt):
        _collect_runtime_name_uses_expr(stmt.cond, out)
        for s in stmt.then_body:
            _collect_runtime_name_uses_stmt(s, out)
        for s in stmt.else_body:
            _collect_runtime_name_uses_stmt(s, out)
        return
    if isinstance(stmt, MatchStmt):
        _collect_runtime_name_uses_expr(stmt.expr, out)
        for pat, body in stmt.arms:
            _collect_runtime_name_uses_expr(pat, out)
            for s in body:
                _collect_runtime_name_uses_stmt(s, out)
        return
    if isinstance(stmt, WhileStmt):
        _collect_runtime_name_uses_expr(stmt.cond, out)
        for s in stmt.body:
            _collect_runtime_name_uses_stmt(s, out)
        return
    if isinstance(stmt, ForStmt):
        _collect_runtime_name_uses_expr(stmt.iterable, out)
        for s in stmt.body:
            _collect_runtime_name_uses_stmt(s, out)
        return
    # Intentionally skip names used only inside comptime blocks; those do not require runtime materialization.
    if isinstance(stmt, ComptimeStmt):
        return
    if isinstance(stmt, UnsafeStmt):
        for s in stmt.body:
            _collect_runtime_name_uses_stmt(s, out)
        return


def _collect_runtime_name_uses(stmts: list[Any]) -> set[str]:
    out: set[str] = set()
    for st in stmts:
        _collect_runtime_name_uses_stmt(st, out)
    return out


def run_comptime(prog: Program, filename: str = "<input>", overflow_mode: str = "trap") -> dict[str, object]:
    """Evaluate compile-time blocks and rewrite AST values with results.

    Parameters:
        prog: Program AST to read or mutate.
        filename: Filename context used for diagnostics or path resolution.
        overflow_mode: Integer overflow behavior mode requested by the caller.

    Returns:
        Value described by the function return annotation.
    """
    fn_map = {item.name: item for item in prog.items if isinstance(item, FnDecl)}
    structs = {item.name: item for item in prog.items if isinstance(item, StructDecl)}
    evaluator = _Evaluator(fn_map, structs, filename=filename, overflow_mode=overflow_mode)
    const_pool: dict[str, object] = {}

    for item in prog.items:
        if not isinstance(item, FnDecl):
            continue
        new_body: list[Any] = []
        known_locals: set[str] = {n for n, _ in item.params}
        env: dict[str, object] = {}
        env_types: dict[str, str] = {n: canonical_type(t) for n, t in item.params}
        for idx, st in enumerate(item.body):
            if isinstance(st, ComptimeStmt):
                snap = copy.deepcopy(env)
                for inner in st.body:
                    sig = evaluator.exec_stmt(inner, env, env_types)
                    if isinstance(sig, _LoopSignal):
                        raise ComptimeError(_diag(filename, st.line, st.col, "return/break/continue cannot escape comptime block"))
                changed = {k: v for k, v in env.items() if k not in snap or snap[k] != v}
                future_runtime_uses = _collect_runtime_name_uses(item.body[idx + 1 :])
                for name, value in changed.items():
                    const_pool[f"{item.name}:{name}"] = value
                    must_materialize = name in known_locals or name in future_runtime_uses
                    if not must_materialize:
                        continue
                    try:
                        expr = _ast_of(value, st)
                    except ComptimeError as err:
                        raise ComptimeError(
                            _diag(filename, st.line, st.col, f"cannot materialize comptime value for {name}: {err}")
                        ) from err
                    if name in known_locals:
                        new_body.append(AssignStmt(Name(name, st.pos, st.line, st.col), "=", expr, st.pos, st.line, st.col))
                    else:
                        known_locals.add(name)
                        new_body.append(LetStmt(name, expr, False, None, st.pos, st.line, st.col))
                continue
            new_body.append(st)
            if isinstance(st, LetStmt):
                known_locals.add(st.name)
                if st.type_name is not None:
                    env_types[st.name] = canonical_type(st.type_name)
                try:
                    env[st.name] = evaluator.eval_expr(st.expr, env, env_types)
                    if st.type_name is None:
                        inferred = _value_type_name(env[st.name])
                        if inferred is not None:
                            env_types[st.name] = inferred
                except ComptimeError:
                    pass
            elif isinstance(st, AssignStmt) and isinstance(st.target, Name):
                try:
                    env[st.target.value] = evaluator.eval_expr(st.expr, env, env_types)
                    if st.op == "=" and st.target.value not in env_types:
                        inferred = _value_type_name(env[st.target.value])
                        if inferred is not None:
                            env_types[st.target.value] = inferred
                except ComptimeError:
                    pass
        item.body = new_body
    return const_pool
