from __future__ import annotations

from dataclasses import dataclass
import math

from astra.ast import *
from astra.layout import LayoutError, canonical_type, layout_of_type


class ComptimeError(Exception):
    pass


def _diag(filename: str, line: int, col: int, msg: str) -> str:
    return f"SEM {filename}:{line}:{col}: comptime: {msg}"


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
            "proc_run",
            "proc_exit",
            "env_get",
            "cwd",
        }

    def _tick(self, node):
        self.steps += 1
        if self.steps > self.max_steps:
            raise ComptimeError(_diag(self.filename, getattr(node, "line", 0), getattr(node, "col", 0), "step limit exceeded"))

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
        if isinstance(e, SizeOfValueExpr):
            return self._layout_for_value_expr(e.expr, env, env_types).size
        if isinstance(e, AlignOfValueExpr):
            return self._layout_for_value_expr(e.expr, env, env_types).align
        if isinstance(e, Name):
            if e.value not in env:
                raise ComptimeError(_diag(self.filename, e.line, e.col, f"undefined name {e.value}"))
            return env[e.value]
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
        if isinstance(e, Call):
            if not isinstance(e.fn, Name):
                raise ComptimeError(_diag(self.filename, e.line, e.col, "comptime only supports direct function calls"))
            name = e.fn.value
            args = [self.eval_expr(a, env, env_types) for a in e.args]
            if name in self.banned:
                raise ComptimeError(_diag(self.filename, e.line, e.col, f"call to non-pure function {name}"))
            if name == "len":
                return len(args[0])
            if name == "alloc":
                ptr = self.next_ptr
                self.next_ptr += 1
                self.heap[ptr] = bytearray(max(0, int(args[0])))
                return ptr
            if name == "free":
                self.heap.pop(int(args[0]), None)
                return 0
            if name in self.fn_map:
                arg_types = [self._expr_type_hint(a, env, env_types) for a in e.args]
                return self.call_user_fn(self.fn_map[name], args, arg_types=arg_types, depth=0)
            raise ComptimeError(_diag(self.filename, e.line, e.col, f"unsupported comptime function {name}"))
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
            return "&str"
        if isinstance(expr, Name):
            if expr.value in env_types:
                return canonical_type(env_types[expr.value])
            val = env.get(expr.value)
            if isinstance(val, bool):
                return "Bool"
            if isinstance(val, int):
                return "Int"
            if isinstance(val, float):
                return "Float"
            return None
        if isinstance(expr, CastExpr):
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
        if ty in {"Int", "isize", "usize", "i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "i128", "u128"}:
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
        return _truncate_int(iv, bits, signed)

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
            if st.init is not None:
                if isinstance(st.init, LetStmt):
                    self.exec_stmt(st.init, env, env_types)
                elif isinstance(st.init, AssignStmt):
                    self.exec_stmt(st.init, env, env_types)
                else:
                    self.eval_expr(st.init, env, env_types)
            while True:
                if st.cond is not None and not bool(self.eval_expr(st.cond, env, env_types)):
                    break
                for s in st.body:
                    sig = self.exec_stmt(s, env, env_types)
                    if not isinstance(sig, _LoopSignal):
                        continue
                    if sig.kind == "continue":
                        break
                    if sig.kind == "break":
                        return None
                    return sig
                if st.step is not None:
                    if isinstance(st.step, AssignStmt):
                        self.exec_stmt(st.step, env, env_types)
                    else:
                        self.eval_expr(st.step, env, env_types)
            return None
        if isinstance(st, ComptimeStmt):
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
    t = canonical_type(typ)
    if t in {"Int", "isize"}:
        return 64, True
    if t == "usize":
        return 64, False
    if t.startswith("i") and t[1:].isdigit():
        return int(t[1:]), True
    if t.startswith("u") and t[1:].isdigit():
        return int(t[1:]), False
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
    t = canonical_type(typ)
    if t in {"Int", "isize", "usize"}:
        return True
    if t.startswith("i") and t[1:].isdigit():
        return True
    if t.startswith("u") and t[1:].isdigit():
        return True
    return False


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


def run_comptime(prog: Program, filename: str = "<input>", overflow_mode: str = "trap") -> dict[str, object]:
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
        for st in item.body:
            if isinstance(st, ComptimeStmt):
                snap = dict(env)
                for inner in st.body:
                    sig = evaluator.exec_stmt(inner, env, env_types)
                    if isinstance(sig, _LoopSignal):
                        raise ComptimeError(_diag(filename, st.line, st.col, "return/break/continue cannot escape comptime block"))
                changed = {k: v for k, v in env.items() if snap.get(k, object()) is not v or k not in snap}
                for name, value in changed.items():
                    const_pool[f"{item.name}:{name}"] = value
                    expr = _ast_of(value, st)
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
