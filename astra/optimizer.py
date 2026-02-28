def optimize(ir):
    for fn in ir.funcs:
        fn.ops = [_fold(op) for op in fn.ops]
    return ir

def _fold(op):
    if op[0] in {"let","expr","ret"} and isinstance(op[-1], tuple):
        return (op[0],) + op[1:-1] + (_fold_expr(op[-1]),)
    return op

def _fold_expr(e):
    if not isinstance(e, tuple): return e
    if e[0]=="bin":
        l = _fold_expr(e[2]); r = _fold_expr(e[3])
        if l[0]=="lit" and r[0]=="lit" and isinstance(l[1], int) and isinstance(r[1], int):
            a,b=l[1],r[1]
            return ("lit", {"+":a+b,"-":a-b,"*":a*b,"/":a//b}.get(e[1], a))
        return ("bin", e[1], l, r)
    return e
