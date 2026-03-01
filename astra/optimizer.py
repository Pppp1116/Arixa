from __future__ import annotations

from typing import Any

from astra.ast import *


def optimize(ir):
    for fn in ir.funcs:
        fn.ops = _optimize_ops(fn.ops)
    return ir


def _optimize_ops(ops):
    out = []
    terminated = False
    for op in ops:
        if terminated:
            continue
        kind = op[0]
        if kind in {"let", "expr", "ret"} and isinstance(op[-1], tuple):
            op = (op[0],) + op[1:-1] + (_fold_expr(op[-1]),)
        elif kind == "assign":
            op = ("assign", _fold_expr(op[1]), op[2], _fold_expr(op[3]))
        elif kind == "if":
            cond = _fold_expr(op[1])
            then_ops = _optimize_ops(op[2])
            else_ops = _optimize_ops(op[3])
            if cond == ("lit", True):
                out.extend(then_ops)
                continue
            if cond == ("lit", False):
                out.extend(else_ops)
                continue
            op = ("if", cond, then_ops, else_ops)
        elif kind == "while":
            cond = _fold_expr(op[1])
            body = _optimize_ops(op[2])
            if cond == ("lit", False):
                continue
            op = ("while", cond, body)
        elif kind == "for":
            init = _optimize_ops(op[1])
            cond = _fold_expr(op[2]) if op[2] is not None else None
            step = _optimize_ops(op[3])
            body = _optimize_ops(op[4])
            if cond == ("lit", False):
                out.extend(init)
                continue
            op = ("for", init, cond, step, body)
        elif kind == "match":
            target = _fold_expr(op[1])
            arms = [(pat, _optimize_ops(body)) for pat, body in op[2]]
            if target and target[0] == "lit":
                matched = None
                for pat, body in arms:
                    if pat == target:
                        matched = body
                        break
                if matched is not None:
                    out.extend(matched)
                    continue
            op = ("match", target, arms)
        out.append(op)
        if op[0] == "ret":
            terminated = True
    return out


def _fold_expr(e):
    if not isinstance(e, tuple):
        return e
    if e[0] == "await":
        return ("await", _fold_expr(e[1]))
    if e[0] == "un":
        inner = _fold_expr(e[2])
        if inner and inner[0] == "lit":
            if e[1] == "-":
                return ("lit", -inner[1])
            if e[1] == "!":
                return ("lit", not bool(inner[1]))
        return ("un", e[1], inner)
    if e[0] == "bin":
        l = _fold_expr(e[2])
        r = _fold_expr(e[3])
        if l and r and l[0] == "lit" and r[0] == "lit":
            a, b = l[1], r[1]
            if isinstance(a, (int, bool, float)) and isinstance(b, (int, bool, float)):
                if e[1] == "+":
                    return ("lit", a + b)
                if e[1] == "-":
                    return ("lit", a - b)
                if e[1] == "*":
                    return ("lit", a * b)
                if e[1] == "/" and b != 0:
                    return ("lit", a // b if isinstance(a, int) and isinstance(b, int) else a / b)
                if e[1] == "%":
                    return ("lit", a % b)
                if e[1] == "&":
                    return ("lit", int(a) & int(b))
                if e[1] == "|":
                    return ("lit", int(a) | int(b))
                if e[1] == "^":
                    return ("lit", int(a) ^ int(b))
                if e[1] == "<<":
                    return ("lit", int(a) << int(b))
                if e[1] == ">>":
                    return ("lit", int(a) >> int(b))
                if e[1] == "==":
                    return ("lit", a == b)
                if e[1] == "!=":
                    return ("lit", a != b)
                if e[1] == "<":
                    return ("lit", a < b)
                if e[1] == "<=":
                    return ("lit", a <= b)
                if e[1] == ">":
                    return ("lit", a > b)
                if e[1] == ">=":
                    return ("lit", a >= b)
                if e[1] == "&&":
                    return ("lit", bool(a) and bool(b))
                if e[1] == "||":
                    return ("lit", bool(a) or bool(b))
        return ("bin", e[1], l, r)
    if e[0] == "cast":
        return ("cast", _fold_expr(e[1]), e[2])
    if e[0] in {"sizeof_type", "alignof_type"}:
        return e
    if e[0] in {"sizeof_value", "alignof_value"}:
        return (e[0], _fold_expr(e[1]))
    if e[0] in {"call", "index", "field", "array"}:
        return tuple(_fold_expr(x) if isinstance(x, tuple) else x for x in e)
    return e


def optimize_program(prog: Program) -> Program:
    for item in prog.items:
        if isinstance(item, FnDecl):
            for _ in range(8):
                before = repr(item.body)
                mutable_names = _collect_mutable_names(item.body)
                body, _ = _optimize_stmts(item.body, {}, mutable_names)
                body, _ = _dse_stmts(body, set())
                item.body = body
                if repr(item.body) == before:
                    break
    return prog


def _optimize_stmts(stmts: list[Any], env: dict[str, Any], mutable_names: set[str]) -> tuple[list[Any], dict[str, Any]]:
    out: list[Any] = []
    cur_env = dict(env)
    for st in stmts:
        lowered, cur_env, terminated = _optimize_stmt(st, cur_env, mutable_names)
        if lowered is None:
            continue
        if isinstance(lowered, list):
            out.extend(lowered)
        else:
            out.append(lowered)
        if terminated:
            break
    return out, cur_env


def _optimize_stmt(st: Any, env: dict[str, Any], mutable_names: set[str]) -> tuple[Any | None, dict[str, Any], bool]:
    if isinstance(st, LetStmt):
        st.expr = _fold_ast_expr(st.expr, env, mutable_names)
        lit = _literal_value(st.expr)
        if lit is _NO_LITERAL or st.name in mutable_names:
            env.pop(st.name, None)
        else:
            env[st.name] = _literal_node(lit, st.expr)
        return st, env, False
    if isinstance(st, AssignStmt):
        st.target = _fold_target_expr(st.target, env, mutable_names)
        st.expr = _fold_ast_expr(st.expr, env, mutable_names)
        if isinstance(st.target, Name):
            if st.target.value in mutable_names:
                env.pop(st.target.value, None)
            elif st.op == "=":
                lit = _literal_value(st.expr)
                if lit is _NO_LITERAL:
                    env.pop(st.target.value, None)
                else:
                    env[st.target.value] = _literal_node(lit, st.expr)
            elif st.op in {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}:
                left = _literal_value(env.get(st.target.value))
                right = _literal_value(st.expr)
                merged = _eval_binary_const(st.op[:-1], left, right)
                if merged is _NO_LITERAL:
                    env.pop(st.target.value, None)
                else:
                    env[st.target.value] = _literal_node(merged, st.expr)
            else:
                env.pop(st.target.value, None)
        else:
            env.clear()
        return st, env, False
    if isinstance(st, ExprStmt):
        st.expr = _fold_ast_expr(st.expr, env, mutable_names)
        if _is_discardable_expr(st.expr):
            return None, env, False
        return st, env, False
    if isinstance(st, DropStmt):
        st.expr = _fold_ast_expr(st.expr, env, mutable_names)
        return st, env, False
    if isinstance(st, ReturnStmt):
        if st.expr is not None:
            st.expr = _fold_ast_expr(st.expr, env, mutable_names)
        return st, env, True
    if isinstance(st, IfStmt):
        st.cond = _fold_ast_expr(st.cond, env, mutable_names)
        cond = _literal_value(st.cond)
        if isinstance(cond, bool):
            branch = st.then_body if cond else st.else_body
            branch_out, branch_env = _optimize_stmts(branch, dict(env), mutable_names)
            return branch_out, branch_env, _stmts_terminate(branch_out)
        then_out, then_env = _optimize_stmts(st.then_body, dict(env), mutable_names)
        else_out, else_env = _optimize_stmts(st.else_body, dict(env), mutable_names)
        st.then_body = then_out
        st.else_body = else_out
        merged = _merge_env(then_env, else_env)
        terminated = bool(st.else_body) and _stmts_terminate(then_out) and _stmts_terminate(else_out)
        return st, merged, terminated
    if isinstance(st, WhileStmt):
        st.cond = _fold_ast_expr(st.cond, env, mutable_names)
        cond = _literal_value(st.cond)
        if cond is False:
            return None, env, False
        body_out, _ = _optimize_stmts(st.body, dict(env), mutable_names)
        st.body = body_out
        env.clear()
        return st, env, False
    if isinstance(st, ForStmt):
        prefix: list[Any] = []
        cur_env = dict(env)
        if st.init is not None:
            if isinstance(st.init, LetStmt):
                init_out, cur_env, _ = _optimize_stmt(st.init, cur_env, mutable_names)
                if init_out is not None:
                    prefix.extend(init_out if isinstance(init_out, list) else [init_out])
                st.init = None
            else:
                st.init = _fold_ast_expr(st.init, cur_env, mutable_names)
        if st.cond is not None:
            st.cond = _fold_ast_expr(st.cond, cur_env, mutable_names)
        if st.step is not None:
            if isinstance(st.step, AssignStmt):
                step_out, _, _ = _optimize_stmt(st.step, dict(cur_env), mutable_names)
                st.step = step_out if isinstance(step_out, AssignStmt) else None
            else:
                st.step = _fold_ast_expr(st.step, cur_env, mutable_names)
        cond = _literal_value(st.cond)
        if cond is False:
            return prefix, cur_env, False
        body_out, _ = _optimize_stmts(st.body, dict(cur_env), mutable_names)
        st.body = body_out
        cur_env.clear()
        if prefix:
            return prefix + [st], cur_env, False
        return st, cur_env, False
    if isinstance(st, MatchStmt):
        st.expr = _fold_ast_expr(st.expr, env, mutable_names)
        target = _literal_value(st.expr)
        if target is not _NO_LITERAL:
            for pat, body in st.arms:
                folded_pat = _fold_ast_expr(pat, env, mutable_names)
                if _literal_value(folded_pat) == target:
                    arm_out, arm_env = _optimize_stmts(body, dict(env), mutable_names)
                    return arm_out, arm_env, _stmts_terminate(arm_out)
        new_arms: list[tuple[Any, list[Any]]] = []
        merged_env: dict[str, Any] | None = None
        for pat, body in st.arms:
            folded_pat = _fold_ast_expr(pat, env, mutable_names)
            arm_out, arm_env = _optimize_stmts(body, dict(env), mutable_names)
            new_arms.append((folded_pat, arm_out))
            merged_env = arm_env if merged_env is None else _merge_env(merged_env, arm_env)
        st.arms = new_arms
        return st, merged_env or {}, False
    if isinstance(st, ComptimeStmt):
        body_out, _ = _optimize_stmts(st.body, dict(env), mutable_names)
        st.body = body_out
        return st, env, False
    if isinstance(st, (BreakStmt, ContinueStmt)):
        return st, env, True
    if isinstance(st, DeferStmt):
        st.expr = _fold_ast_expr(st.expr, env, mutable_names)
        return st, env, False
    return st, env, False


def _merge_env(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, aval in a.items():
        if key not in b:
            continue
        if _literal_value(aval) == _literal_value(b[key]):
            out[key] = aval
    return out


def _stmts_terminate(stmts: list[Any]) -> bool:
    if not stmts:
        return False
    return isinstance(stmts[-1], (ReturnStmt, BreakStmt, ContinueStmt))


def _fold_target_expr(target: Any, env: dict[str, Any], mutable_names: set[str]) -> Any:
    if isinstance(target, IndexExpr):
        target.obj = _fold_ast_expr(target.obj, env, mutable_names)
        target.index = _fold_ast_expr(target.index, env, mutable_names)
        return target
    if isinstance(target, FieldExpr):
        target.obj = _fold_ast_expr(target.obj, env, mutable_names)
        return target
    return target


def _fold_ast_expr(expr: Any, env: dict[str, Any], mutable_names: set[str]) -> Any:
    if isinstance(expr, Name):
        if expr.value in env and expr.value not in mutable_names:
            return _literal_node(_literal_value(env[expr.value]), expr)
        return expr
    if isinstance(expr, (Literal, BoolLit, NilLit)):
        return expr
    if isinstance(expr, Unary):
        expr.expr = _fold_ast_expr(expr.expr, env, mutable_names)
        value = _literal_value(expr.expr)
        if value is _NO_LITERAL:
            return expr
        if expr.op == "-":
            if isinstance(value, (int, float)):
                return _literal_node(-value, expr)
            return expr
        if expr.op == "!":
            return _literal_node(not bool(value), expr)
        return expr
    if isinstance(expr, Binary):
        expr.left = _fold_ast_expr(expr.left, env, mutable_names)
        expr.right = _fold_ast_expr(expr.right, env, mutable_names)
        lval = _literal_value(expr.left)
        rval = _literal_value(expr.right)
        out = _eval_binary_const(expr.op, lval, rval)
        if out is not _NO_LITERAL:
            return _literal_node(out, expr)
        # Algebraic simplifications that preserve evaluation order.
        if expr.op == "+":
            if rval == 0 and _is_pure_expr(expr.left):
                return expr.left
            if lval == 0 and _is_pure_expr(expr.right):
                return expr.right
        if expr.op == "-":
            if rval == 0 and _is_pure_expr(expr.left):
                return expr.left
        if expr.op == "*":
            if rval == 1 and _is_pure_expr(expr.left):
                return expr.left
            if lval == 1 and _is_pure_expr(expr.right):
                return expr.right
            if rval == 0 and _is_discardable_expr(expr.left):
                return _literal_node(0, expr)
            if lval == 0 and _is_discardable_expr(expr.right):
                return _literal_node(0, expr)
        if expr.op == "/":
            if rval == 1 and _is_pure_expr(expr.left):
                return expr.left
        if expr.op in {"|", "^"}:
            if rval == 0 and _is_pure_expr(expr.left):
                return expr.left
            if lval == 0 and _is_pure_expr(expr.right):
                return expr.right
        if expr.op == "&":
            if rval == -1 and _is_pure_expr(expr.left):
                return expr.left
            if lval == -1 and _is_pure_expr(expr.right):
                return expr.right
        if expr.op == "??":
            if lval is None:
                return expr.right
            if lval is not _NO_LITERAL:
                return expr.left
        if expr.op == "&&" and isinstance(lval, bool):
            if not lval:
                return _literal_node(False, expr)
            return expr.right
        if expr.op == "||" and isinstance(lval, bool):
            if lval:
                return _literal_node(True, expr)
            return expr.right
        return expr
    if isinstance(expr, Call):
        expr.fn = _fold_ast_expr(expr.fn, env, mutable_names)
        expr.args = [_fold_ast_expr(arg, env, mutable_names) for arg in expr.args]
        return expr
    if isinstance(expr, AwaitExpr):
        expr.expr = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr
    if isinstance(expr, IndexExpr):
        expr.obj = _fold_ast_expr(expr.obj, env, mutable_names)
        expr.index = _fold_ast_expr(expr.index, env, mutable_names)
        return expr
    if isinstance(expr, FieldExpr):
        expr.obj = _fold_ast_expr(expr.obj, env, mutable_names)
        return expr
    if isinstance(expr, ArrayLit):
        expr.elements = [_fold_ast_expr(e, env, mutable_names) for e in expr.elements]
        return expr
    if isinstance(expr, StructLit):
        expr.fields = [(name, _fold_ast_expr(value, env, mutable_names)) for name, value in expr.fields]
        return expr
    if isinstance(expr, TypeAnnotated):
        expr.expr = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr
    if isinstance(expr, CastExpr):
        expr.expr = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr
    if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr)):
        return expr
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        expr.expr = _fold_ast_expr(expr.expr, env, mutable_names)
        return expr
    return expr


_NO_LITERAL = object()


def _literal_value(expr: Any) -> Any:
    if isinstance(expr, BoolLit):
        return bool(expr.value)
    if isinstance(expr, NilLit):
        return None
    if isinstance(expr, Literal):
        return expr.value
    return _NO_LITERAL


def _literal_node(value: Any, src: Any) -> Any:
    pos = getattr(src, "pos", 0)
    line = getattr(src, "line", 0)
    col = getattr(src, "col", 0)
    if value is None:
        return NilLit(pos=pos, line=line, col=col)
    if isinstance(value, bool):
        return BoolLit(value=value, pos=pos, line=line, col=col)
    return Literal(value=value, pos=pos, line=line, col=col)


def _is_pure_expr(expr: Any) -> bool:
    if isinstance(expr, (Name, Literal, BoolLit, NilLit)):
        return True
    if isinstance(expr, Unary):
        return _is_pure_expr(expr.expr)
    if isinstance(expr, Binary):
        return _is_pure_expr(expr.left) and _is_pure_expr(expr.right)
    if isinstance(expr, ArrayLit):
        return all(_is_pure_expr(e) for e in expr.elements)
    if isinstance(expr, StructLit):
        return all(_is_pure_expr(v) for _, v in expr.fields)
    if isinstance(expr, TypeAnnotated):
        return _is_pure_expr(expr.expr)
    if isinstance(expr, CastExpr):
        return _is_pure_expr(expr.expr)
    if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr)):
        return True
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        return _is_pure_expr(expr.expr)
    return False


def _is_discardable_expr(expr: Any) -> bool:
    return _is_pure_expr(expr) and not _may_trap_expr(expr)


def _may_trap_expr(expr: Any) -> bool:
    if isinstance(expr, (Literal, BoolLit, NilLit, Name)):
        return False
    if isinstance(expr, Unary):
        return _may_trap_expr(expr.expr)
    if isinstance(expr, Binary):
        if _may_trap_expr(expr.left) or _may_trap_expr(expr.right):
            return True
        if expr.op in {"/", "%"}:
            rval = _literal_value(expr.right)
            if rval is _NO_LITERAL:
                return True
            return rval == 0
        return False
    if isinstance(expr, ArrayLit):
        return any(_may_trap_expr(e) for e in expr.elements)
    if isinstance(expr, StructLit):
        return any(_may_trap_expr(v) for _, v in expr.fields)
    if isinstance(expr, TypeAnnotated):
        return _may_trap_expr(expr.expr)
    if isinstance(expr, CastExpr):
        return _may_trap_expr(expr.expr)
    if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr)):
        return False
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        return _may_trap_expr(expr.expr)
    # Conservative: calls/await/index/field are observable or may trap.
    return True


def _eval_binary_const(op: str, left: Any, right: Any) -> Any:
    if left is _NO_LITERAL or right is _NO_LITERAL:
        return _NO_LITERAL
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/" and right != 0:
        if isinstance(left, int) and isinstance(right, int):
            return left // right
        return left / right
    if op == "%" and right != 0:
        return left % right
    if op == "&":
        return int(left) & int(right)
    if op == "|":
        return int(left) | int(right)
    if op == "^":
        return int(left) ^ int(right)
    if op == "<<":
        return int(left) << int(right)
    if op == ">>":
        return int(left) >> int(right)
    if op == "==":
        return left == right
    if op == "!=":
        return left != right
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    if op == ">=":
        return left >= right
    if op == "&&":
        return bool(left) and bool(right)
    if op == "||":
        return bool(left) or bool(right)
    if op == "??":
        return right if left is None else left
    return _NO_LITERAL


def _collect_mutable_names(stmts: list[Any]) -> set[str]:
    out: set[str] = set()

    def walk(items: list[Any]):
        for st in items:
            if isinstance(st, LetStmt):
                if st.mut:
                    out.add(st.name)
            elif isinstance(st, AssignStmt):
                if isinstance(st.target, Name):
                    out.add(st.target.value)
            elif isinstance(st, IfStmt):
                walk(st.then_body)
                walk(st.else_body)
            elif isinstance(st, WhileStmt):
                walk(st.body)
            elif isinstance(st, ForStmt):
                if isinstance(st.init, LetStmt) and st.init.mut:
                    out.add(st.init.name)
                if isinstance(st.step, AssignStmt) and isinstance(st.step.target, Name):
                    out.add(st.step.target.value)
                walk(st.body)
            elif isinstance(st, MatchStmt):
                for _, body in st.arms:
                    walk(body)
            elif isinstance(st, ComptimeStmt):
                walk(st.body)

    walk(stmts)
    return out


def _dse_stmts(stmts: list[Any], live_out: set[str]) -> tuple[list[Any], set[str]]:
    live = set(live_out)
    out_rev: list[Any] = []
    for st in reversed(stmts):
        if isinstance(st, ReturnStmt):
            out_rev.append(st)
            live = _used_names_expr(st.expr) if st.expr is not None else set()
            continue
        if isinstance(st, ExprStmt):
            if _is_discardable_expr(st.expr):
                continue
            out_rev.append(st)
            live |= _used_names_expr(st.expr)
            continue
        if isinstance(st, DropStmt):
            out_rev.append(st)
            live |= _used_names_expr(st.expr)
            continue
        if isinstance(st, LetStmt):
            uses = _used_names_expr(st.expr)
            if st.name not in live:
                if _is_discardable_expr(st.expr):
                    continue
                out_rev.append(ExprStmt(expr=st.expr, pos=st.pos, line=st.line, col=st.col))
                live |= uses
                continue
            out_rev.append(st)
            live.discard(st.name)
            live |= uses
            continue
        if isinstance(st, AssignStmt):
            if isinstance(st.target, Name) and st.op == "=" and st.target.value not in live:
                if _is_discardable_expr(st.expr):
                    continue
                out_rev.append(ExprStmt(expr=st.expr, pos=st.pos, line=st.line, col=st.col))
                live |= _used_names_expr(st.expr)
                continue
            out_rev.append(st)
            uses = _used_names_expr(st.expr) | _used_names_target(st.target)
            if isinstance(st.target, Name):
                if st.op == "=":
                    live.discard(st.target.value)
                    live |= uses
                elif st.op in {"+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}:
                    # Compound assignments read the previous target value.
                    live |= uses | {st.target.value}
                else:
                    live |= uses
            else:
                live |= uses
            continue
        if isinstance(st, IfStmt):
            then_body, then_live = _dse_stmts(st.then_body, set(live))
            else_body, else_live = _dse_stmts(st.else_body, set(live))
            st.then_body = then_body
            st.else_body = else_body
            cond_uses = _used_names_expr(st.cond)
            if not st.then_body and not st.else_body and _is_discardable_expr(st.cond):
                live |= then_live | else_live
                continue
            out_rev.append(st)
            live = cond_uses | then_live | else_live
            continue
        if isinstance(st, MatchStmt):
            arm_lives: list[set[str]] = []
            new_arms: list[tuple[Any, list[Any]]] = []
            for pat, body in st.arms:
                body_out, arm_live = _dse_stmts(body, set(live))
                new_arms.append((pat, body_out))
                arm_lives.append(arm_live | _used_names_expr(pat))
            st.arms = new_arms
            out_rev.append(st)
            cond_live = _used_names_expr(st.expr)
            combined = set(cond_live)
            for arm_live in arm_lives:
                combined |= arm_live
            live = combined
            continue
        if isinstance(st, WhileStmt):
            loop_live_seed = set(live) | _used_names_expr(st.cond) | _names_assigned_stmts(st.body)
            body_out, body_live = _dse_stmts(st.body, loop_live_seed)
            st.body = body_out
            out_rev.append(st)
            live = set(live) | _used_names_expr(st.cond) | body_live | _names_assigned_stmts(st.body)
            continue
        if isinstance(st, ForStmt):
            loop_seed = set(live) | _names_assigned_stmts(st.body)
            if st.cond is not None:
                loop_seed |= _used_names_expr(st.cond)
            if st.step is not None:
                if isinstance(st.step, AssignStmt):
                    loop_seed |= _used_names_expr(st.step.expr) | _used_names_target(st.step.target)
                else:
                    loop_seed |= _used_names_expr(st.step)
            body_out, body_live = _dse_stmts(st.body, loop_seed)
            st.body = body_out
            out_rev.append(st)
            live |= body_live
            if st.init is not None:
                if isinstance(st.init, LetStmt):
                    live |= _used_names_expr(st.init.expr)
                else:
                    live |= _used_names_expr(st.init)
            if st.cond is not None:
                live |= _used_names_expr(st.cond)
            if st.step is not None:
                if isinstance(st.step, AssignStmt):
                    live |= _used_names_expr(st.step.expr) | _used_names_target(st.step.target)
                    if isinstance(st.step.target, Name):
                        live.add(st.step.target.value)
                else:
                    live |= _used_names_expr(st.step)
            continue
        if isinstance(st, ComptimeStmt):
            body_out, body_live = _dse_stmts(st.body, set(live))
            st.body = body_out
            out_rev.append(st)
            live |= body_live
            continue
        if isinstance(st, DeferStmt):
            out_rev.append(st)
            live |= _used_names_expr(st.expr)
            continue
        if isinstance(st, (BreakStmt, ContinueStmt)):
            out_rev.append(st)
            continue
        out_rev.append(st)
    out_rev.reverse()
    return out_rev, live


def _used_names_expr(expr: Any) -> set[str]:
    if isinstance(expr, Name):
        return {expr.value}
    if isinstance(expr, (Literal, BoolLit, NilLit)):
        return set()
    if isinstance(expr, Unary):
        return _used_names_expr(expr.expr)
    if isinstance(expr, Binary):
        return _used_names_expr(expr.left) | _used_names_expr(expr.right)
    if isinstance(expr, Call):
        out = _used_names_expr(expr.fn)
        for arg in expr.args:
            out |= _used_names_expr(arg)
        return out
    if isinstance(expr, AwaitExpr):
        return _used_names_expr(expr.expr)
    if isinstance(expr, IndexExpr):
        return _used_names_expr(expr.obj) | _used_names_expr(expr.index)
    if isinstance(expr, FieldExpr):
        return _used_names_expr(expr.obj)
    if isinstance(expr, ArrayLit):
        out: set[str] = set()
        for elem in expr.elements:
            out |= _used_names_expr(elem)
        return out
    if isinstance(expr, StructLit):
        out: set[str] = set()
        for _, value in expr.fields:
            out |= _used_names_expr(value)
        return out
    if isinstance(expr, TypeAnnotated):
        return _used_names_expr(expr.expr)
    if isinstance(expr, CastExpr):
        return _used_names_expr(expr.expr)
    if isinstance(expr, (SizeOfTypeExpr, AlignOfTypeExpr)):
        return set()
    if isinstance(expr, (SizeOfValueExpr, AlignOfValueExpr)):
        return _used_names_expr(expr.expr)
    return set()


def _used_names_target(target: Any) -> set[str]:
    if isinstance(target, Name):
        return set()
    if isinstance(target, IndexExpr):
        return _used_names_expr(target.obj) | _used_names_expr(target.index)
    if isinstance(target, FieldExpr):
        return _used_names_expr(target.obj)
    return _used_names_expr(target)


def _names_assigned_stmts(stmts: list[Any]) -> set[str]:
    out: set[str] = set()

    def walk(items: list[Any]):
        for st in items:
            if isinstance(st, LetStmt):
                out.add(st.name)
            elif isinstance(st, AssignStmt) and isinstance(st.target, Name):
                out.add(st.target.value)
            elif isinstance(st, IfStmt):
                walk(st.then_body)
                walk(st.else_body)
            elif isinstance(st, WhileStmt):
                walk(st.body)
            elif isinstance(st, ForStmt):
                if isinstance(st.init, LetStmt):
                    out.add(st.init.name)
                if isinstance(st.step, AssignStmt) and isinstance(st.step.target, Name):
                    out.add(st.step.target.value)
                walk(st.body)
            elif isinstance(st, MatchStmt):
                for _, body in st.arms:
                    walk(body)
            elif isinstance(st, ComptimeStmt):
                walk(st.body)

    walk(stmts)
    return out
