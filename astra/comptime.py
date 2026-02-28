from __future__ import annotations

from dataclasses import dataclass

from astra.ast import *


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
    def __init__(self, fn_map: dict[str, FnDecl], filename: str):
        self.fn_map = fn_map
        self.filename = filename
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

    def eval_expr(self, e, env):
        self._tick(e)
        if isinstance(e, Literal):
            return e.value
        if isinstance(e, BoolLit):
            return e.value
        if isinstance(e, NilLit):
            return None
        if isinstance(e, Name):
            if e.value not in env:
                raise ComptimeError(_diag(self.filename, e.line, e.col, f"undefined name {e.value}"))
            return env[e.value]
        if isinstance(e, ArrayLit):
            return [self.eval_expr(x, env) for x in e.elements]
        if isinstance(e, Unary):
            v = self.eval_expr(e.expr, env)
            if e.op == "-":
                return -v
            if e.op == "!":
                return not bool(v)
            if e.op == "~":
                return ~int(v)
            raise ComptimeError(_diag(self.filename, e.line, e.col, f"unsupported unary op {e.op}"))
        if isinstance(e, Binary):
            l = self.eval_expr(e.left, env)
            if e.op == "??":
                return l if l is not None else self.eval_expr(e.right, env)
            r = self.eval_expr(e.right, env)
            if e.op == "+":
                return l + r
            if e.op == "-":
                return l - r
            if e.op == "*":
                return l * r
            if e.op == "/":
                return l // r if isinstance(l, int) and isinstance(r, int) else l / r
            if e.op == "%":
                return l % r
            if e.op == "==":
                return l == r
            if e.op == "!=":
                return l != r
            if e.op == "<":
                return l < r
            if e.op == "<=":
                return l <= r
            if e.op == ">":
                return l > r
            if e.op == ">=":
                return l >= r
            if e.op == "&&":
                return bool(l) and bool(r)
            if e.op == "||":
                return bool(l) or bool(r)
            raise ComptimeError(_diag(self.filename, e.line, e.col, f"unsupported binary op {e.op}"))
        if isinstance(e, IndexExpr):
            o = self.eval_expr(e.obj, env)
            i = int(self.eval_expr(e.index, env))
            return o[i]
        if isinstance(e, FieldExpr):
            o = self.eval_expr(e.obj, env)
            if isinstance(o, dict):
                return o.get(e.field)
            raise ComptimeError(_diag(self.filename, e.line, e.col, "field access only supported for map-like values"))
        if isinstance(e, AwaitExpr):
            return self.eval_expr(e.expr, env)
        if isinstance(e, Call):
            if not isinstance(e.fn, Name):
                raise ComptimeError(_diag(self.filename, e.line, e.col, "comptime only supports direct function calls"))
            name = e.fn.value
            args = [self.eval_expr(a, env) for a in e.args]
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
                return self.call_user_fn(self.fn_map[name], args, depth=0)
            raise ComptimeError(_diag(self.filename, e.line, e.col, f"unsupported comptime function {name}"))
        raise ComptimeError(_diag(self.filename, getattr(e, "line", 0), getattr(e, "col", 0), f"unsupported expression {type(e).__name__}"))

    def exec_stmt(self, st, env):
        self._tick(st)
        if isinstance(st, LetStmt):
            env[st.name] = self.eval_expr(st.expr, env)
            return None
        if isinstance(st, AssignStmt):
            if not isinstance(st.target, Name):
                raise ComptimeError(_diag(self.filename, st.line, st.col, "comptime assignment target must be a name"))
            rhs = self.eval_expr(st.expr, env)
            if st.op == "=":
                env[st.target.value] = rhs
            else:
                cur = env.get(st.target.value)
                if cur is None:
                    raise ComptimeError(_diag(self.filename, st.line, st.col, f"undefined name {st.target.value}"))
                if st.op == "+=":
                    env[st.target.value] = cur + rhs
                elif st.op == "-=":
                    env[st.target.value] = cur - rhs
                elif st.op == "*=":
                    env[st.target.value] = cur * rhs
                elif st.op == "/=":
                    env[st.target.value] = cur // rhs if isinstance(cur, int) and isinstance(rhs, int) else cur / rhs
                elif st.op == "%=":
                    env[st.target.value] = cur % rhs
                else:
                    raise ComptimeError(_diag(self.filename, st.line, st.col, f"unsupported assignment op {st.op}"))
            return None
        if isinstance(st, ExprStmt):
            self.eval_expr(st.expr, env)
            return None
        if isinstance(st, ReturnStmt):
            v = None if st.expr is None else self.eval_expr(st.expr, env)
            return _LoopSignal("return", v)
        if isinstance(st, BreakStmt):
            return _LoopSignal("break")
        if isinstance(st, ContinueStmt):
            return _LoopSignal("continue")
        if isinstance(st, DeferStmt):
            return None
        if isinstance(st, IfStmt):
            branch = st.then_body if bool(self.eval_expr(st.cond, env)) else st.else_body
            for s in branch:
                sig = self.exec_stmt(s, env)
                if isinstance(sig, _LoopSignal):
                    return sig
            return None
        if isinstance(st, WhileStmt):
            while bool(self.eval_expr(st.cond, env)):
                for s in st.body:
                    sig = self.exec_stmt(s, env)
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
                    self.exec_stmt(st.init, env)
                elif isinstance(st.init, AssignStmt):
                    self.exec_stmt(st.init, env)
                else:
                    self.eval_expr(st.init, env)
            while True:
                if st.cond is not None and not bool(self.eval_expr(st.cond, env)):
                    break
                for s in st.body:
                    sig = self.exec_stmt(s, env)
                    if not isinstance(sig, _LoopSignal):
                        continue
                    if sig.kind == "continue":
                        break
                    if sig.kind == "break":
                        return None
                    return sig
                if st.step is not None:
                    if isinstance(st.step, AssignStmt):
                        self.exec_stmt(st.step, env)
                    else:
                        self.eval_expr(st.step, env)
            return None
        if isinstance(st, ComptimeStmt):
            for s in st.body:
                sig = self.exec_stmt(s, env)
                if isinstance(sig, _LoopSignal):
                    return sig
            return None
        raise ComptimeError(_diag(self.filename, getattr(st, "line", 0), getattr(st, "col", 0), f"unsupported statement {type(st).__name__}"))

    def call_user_fn(self, fn: FnDecl, args: list[object], depth: int):
        if depth > 64:
            raise ComptimeError(_diag(self.filename, fn.line, fn.col, "comptime recursion limit exceeded"))
        if fn.async_fn:
            raise ComptimeError(_diag(self.filename, fn.line, fn.col, "async fn cannot run in comptime"))
        if len(args) != len(fn.params):
            raise ComptimeError(_diag(self.filename, fn.line, fn.col, f"{fn.name} expects {len(fn.params)} args, got {len(args)}"))
        env = {name: value for (name, _), value in zip(fn.params, args)}
        for st in fn.body:
            sig = self.exec_stmt(st, env)
            if isinstance(sig, _LoopSignal) and sig.kind == "return":
                return sig.value
        return None


def run_comptime(prog: Program, filename: str = "<input>") -> dict[str, object]:
    fn_map = {item.name: item for item in prog.items if isinstance(item, FnDecl)}
    evaluator = _Evaluator(fn_map, filename=filename)
    const_pool: dict[str, object] = {}
    for item in prog.items:
        if not isinstance(item, FnDecl):
            continue
        new_body: list[Any] = []
        known_locals: set[str] = {n for n, _ in item.params}
        env: dict[str, object] = {}
        for st in item.body:
            if isinstance(st, ComptimeStmt):
                snap = dict(env)
                for inner in st.body:
                    sig = evaluator.exec_stmt(inner, env)
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
                if isinstance(st.expr, (Literal, BoolLit, NilLit, ArrayLit)):
                    try:
                        env[st.name] = evaluator.eval_expr(st.expr, env)
                    except ComptimeError:
                        pass
            elif isinstance(st, AssignStmt) and isinstance(st.target, Name) and isinstance(st.expr, (Literal, BoolLit, NilLit, ArrayLit)):
                try:
                    env[st.target.value] = evaluator.eval_expr(st.expr, env)
                except ComptimeError:
                    pass
        item.body = new_body
    return const_pool
