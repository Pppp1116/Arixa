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
    if e[0] in {"call", "index", "field", "array"}:
        return tuple(_fold_expr(x) if isinstance(x, tuple) else x for x in e)
    return e
