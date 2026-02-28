from dataclasses import dataclass
from astra.ast import *

@dataclass
class IRFn:
    name: str
    ops: list[tuple]

@dataclass
class IR:
    funcs: list[IRFn]

def lower(prog: Program) -> IR:
    funcs=[]
    for fn in prog.items:
        ops=[]
        for st in fn.body:
            ops.extend(_stmt(st))
        funcs.append(IRFn(fn.name, ops))
    return IR(funcs)

def _stmt(st):
    if isinstance(st, LetStmt): return [("let", st.name, _expr(st.expr))]
    if isinstance(st, ReturnStmt): return [("ret", _expr(st.expr) if st.expr else None)]
    if isinstance(st, ExprStmt): return [("expr", _expr(st.expr))]
    if isinstance(st, IfStmt): return [("if", _expr(st.cond), [_stmt(x) for x in st.then_body], [_stmt(x) for x in st.else_body])]
    if isinstance(st, WhileStmt): return [("while", _expr(st.cond), [_stmt(x) for x in st.body])]
    return []

def _expr(e):
    if isinstance(e, Literal): return ("lit", e.value)
    if isinstance(e, Name): return ("name", e.value)
    if isinstance(e, Binary): return ("bin", e.op, _expr(e.left), _expr(e.right))
    if isinstance(e, Call): return ("call", e.fn, [_expr(a) for a in e.args])
    return ("unk",)
