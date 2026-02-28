from astra.ast import *


class SemanticError(Exception):
    pass


BUILTINS = {"print", "len", "read_file", "write_file", "args", "arg"}


def analyze(prog: Program):
    fns = {f.name: f for f in prog.items if isinstance(f, FnDecl)}
    if "main" not in fns:
        raise SemanticError("missing main()")
    for fn in fns.values():
        symbols = {n: t for n, t in fn.params}
        for st in fn.body:
            _check_stmt(st, symbols, fns)


def _check_stmt(st, symbols, fns):
    if isinstance(st, LetStmt):
        symbols[st.name] = _infer(st.expr, symbols, fns)
    elif isinstance(st, AssignStmt):
        _infer(st.expr, symbols, fns)
    elif isinstance(st, ReturnStmt):
        if st.expr:
            _infer(st.expr, symbols, fns)
    elif isinstance(st, IfStmt):
        _infer(st.cond, symbols, fns)
        for s in st.then_body:
            _check_stmt(s, symbols.copy(), fns)
        for s in st.else_body:
            _check_stmt(s, symbols.copy(), fns)
    elif isinstance(st, WhileStmt):
        _infer(st.cond, symbols, fns)
        for s in st.body:
            _check_stmt(s, symbols.copy(), fns)
    elif isinstance(st, ForStmt):
        for s in st.body:
            _check_stmt(s, symbols.copy(), fns)
    elif isinstance(st, ExprStmt):
        _infer(st.expr, symbols, fns)


def _infer(e, symbols, fns):
    if isinstance(e, BoolLit):
        return "Bool"
    if isinstance(e, NilLit):
        return "Nil"
    if isinstance(e, Literal):
        if isinstance(e.value, int):
            return "Int"
        if isinstance(e.value, float):
            return "Float"
        return "String"
    if isinstance(e, Name):
        if e.value not in symbols and e.value not in BUILTINS and e.value not in fns:
            raise SemanticError(f"undefined name {e.value}")
        return symbols.get(e.value, "Any")
    if isinstance(e, Unary):
        return _infer(e.expr, symbols, fns)
    if isinstance(e, Binary):
        _infer(e.left, symbols, fns)
        _infer(e.right, symbols, fns)
        return "Int"
    if isinstance(e, Call):
        fn_name = e.fn.value if isinstance(e.fn, Name) else None
        if fn_name and fn_name in fns:
            for a in e.args:
                _infer(a, symbols, fns)
            return fns[fn_name].ret
        if fn_name and fn_name in BUILTINS:
            return "Int" if fn_name in {"len", "arg"} else "Any"
        raise SemanticError(f"undefined function {fn_name or e.fn}")
    if isinstance(e, IndexExpr):
        _infer(e.obj, symbols, fns)
        _infer(e.index, symbols, fns)
        return "Any"
    if isinstance(e, FieldExpr):
        _infer(e.obj, symbols, fns)
        return "Any"
    if isinstance(e, ArrayLit):
        for el in e.elements:
            _infer(el, symbols, fns)
        return "Any"
    return "Any"
