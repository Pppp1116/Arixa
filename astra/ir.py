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
    funcs = []
    for item in prog.items:
        if not isinstance(item, FnDecl):
            continue
        ops: list[tuple] = []
        for st in item.body:
            ops.extend(_stmt(st))
        funcs.append(IRFn(item.name, ops))
    ir = IR(funcs)
    validate(ir)
    return ir


def validate(ir: IR):
    valid_heads = {"let", "assign", "ret", "expr", "drop", "if", "while", "for", "match"}
    for fn in ir.funcs:
        for op in fn.ops:
            if not isinstance(op, tuple) or not op:
                raise ValueError("malformed IR op")
            if op[0] not in valid_heads:
                raise ValueError(f"unknown IR op {op[0]}")


def _stmt(st):
    if isinstance(st, LetStmt):
        return [("let", st.name, _expr(st.expr))]
    if isinstance(st, AssignStmt):
        return [("assign", _expr(st.target), st.op, _expr(st.expr))]
    if isinstance(st, ReturnStmt):
        return [("ret", _expr(st.expr) if st.expr else None)]
    if isinstance(st, ExprStmt):
        return [("expr", _expr(st.expr))]
    if isinstance(st, DropStmt):
        return [("drop", _expr(st.expr))]
    if isinstance(st, IfStmt):
        then_ops = []
        for x in st.then_body:
            then_ops.extend(_stmt(x))
        else_ops = []
        for x in st.else_body:
            else_ops.extend(_stmt(x))
        return [("if", _expr(st.cond), then_ops, else_ops)]
    if isinstance(st, WhileStmt):
        body = []
        for x in st.body:
            body.extend(_stmt(x))
        return [("while", _expr(st.cond), body)]
    if isinstance(st, ForStmt):
        init = [] if st.init is None else (_stmt(st.init) if isinstance(st.init, LetStmt) else [("expr", _expr(st.init))])
        step = [] if st.step is None else (_stmt(st.step) if isinstance(st.step, AssignStmt) else [("expr", _expr(st.step))])
        body = []
        for x in st.body:
            body.extend(_stmt(x))
        return [("for", init, _expr(st.cond) if st.cond else None, step, body)]
    if isinstance(st, MatchStmt):
        arms: list[tuple] = []
        for pat, body in st.arms:
            arm_ops = []
            for x in body:
                arm_ops.extend(_stmt(x))
            arms.append((_expr(pat), arm_ops))
        return [("match", _expr(st.expr), arms)]
    return []


def _expr(e):
    if isinstance(e, BoolLit):
        return ("lit", e.value)
    if isinstance(e, NilLit):
        return ("none",)
    if isinstance(e, Literal):
        return ("lit", e.value)
    if isinstance(e, Name):
        return ("name", e.value)
    if isinstance(e, AwaitExpr):
        return ("await", _expr(e.expr))
    if isinstance(e, Binary):
        return ("bin", e.op, _expr(e.left), _expr(e.right))
    if isinstance(e, Unary):
        return ("un", e.op, _expr(e.expr))
    if isinstance(e, Call):
        return ("call", _expr(e.fn), [_expr(a) for a in e.args])
    if isinstance(e, IndexExpr):
        return ("index", _expr(e.obj), _expr(e.index))
    if isinstance(e, FieldExpr):
        return ("field", _expr(e.obj), e.field)
    if isinstance(e, ArrayLit):
        return ("array", [_expr(x) for x in e.elements])
    if isinstance(e, CastExpr):
        return ("cast", _expr(e.expr), e.type_name)
    if isinstance(e, SizeOfTypeExpr):
        return ("sizeof_type", e.type_name)
    if isinstance(e, AlignOfTypeExpr):
        return ("alignof_type", e.type_name)
    if isinstance(e, SizeOfValueExpr):
        return ("sizeof_value", _expr(e.expr))
    if isinstance(e, AlignOfValueExpr):
        return ("alignof_value", _expr(e.expr))
    return ("unk",)
