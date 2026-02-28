from astra.ast import *

class SemanticError(Exception):
    pass

def analyze(prog: Program):
    fns = {f.name: f for f in prog.items if isinstance(f, FnDecl)}
    if "main" not in fns:
        raise SemanticError("missing main()")
    for fn in fns.values():
        symbols = {n:t for n,t in fn.params}
        for st in fn.body:
            _check_stmt(st, symbols, fns)

def _check_stmt(st, symbols, fns):
    if isinstance(st, LetStmt):
        symbols[st.name] = _infer(st.expr, symbols, fns)
    elif isinstance(st, ReturnStmt):
        if st.expr: _infer(st.expr, symbols, fns)
    elif isinstance(st, IfStmt):
        _infer(st.cond, symbols, fns)
        for s in st.then_body: _check_stmt(s, symbols.copy(), fns)
        for s in st.else_body: _check_stmt(s, symbols.copy(), fns)
    elif isinstance(st, WhileStmt):
        _infer(st.cond, symbols, fns)
        for s in st.body: _check_stmt(s, symbols.copy(), fns)
    elif isinstance(st, ExprStmt):
        _infer(st.expr, symbols, fns)

def _infer(e, symbols, fns):
    if isinstance(e, Literal): return "Int" if isinstance(e.value,int) else "String"
    if isinstance(e, Name):
        if e.value not in symbols and e.value not in {"print","len","read_file","write_file","args","arg"}:
            raise SemanticError(f"undefined name {e.value}")
        return symbols.get(e.value, "Any")
    if isinstance(e, Binary):
        _infer(e.left, symbols, fns); _infer(e.right, symbols, fns); return "Int"
    if isinstance(e, Call):
        if e.fn in fns:
            for a in e.args: _infer(a, symbols, fns)
            return fns[e.fn].ret
        if e.fn in {"print","len","read_file","write_file","args","arg"}:
            return "Int" if e.fn in {"len","arg"} else "Any"
        raise SemanticError(f"undefined function {e.fn}")
    return "Any"
