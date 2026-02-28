from astra.ast import *


class SemanticError(Exception):
    pass


BUILTINS = {
    "print",
    "len",
    "read_file",
    "write_file",
    "args",
    "arg",
    "spawn",
    "join",
    "alloc",
    "free",
}


class _OwnedState:
    def __init__(self):
        self.owners: dict[str, str] = {}

    def copy(self):
        nxt = _OwnedState()
        nxt.owners = self.owners.copy()
        return nxt

    def track_alloc(self, name: str):
        self.owners[name] = "alive"

    def move(self, src: str, dst: str):
        self._require_alive(src)
        self.owners[src] = "moved"
        self.owners[dst] = "alive"

    def free(self, name: str):
        self._require_alive(name)
        self.owners[name] = "freed"

    def invalidate(self, name: str):
        if name in self.owners and self.owners[name] == "alive":
            self.owners[name] = "moved"

    def assign_name(self, dst: str, src: str):
        if src in self.owners:
            self.move(src, dst)
            return
        if dst in self.owners:
            self._require_reassigned_after_drop(dst)

    def check_use(self, name: str):
        if name in self.owners:
            self._require_alive(name)

    def check_no_live_leaks(self, fn_name: str):
        leaked = sorted(k for k, v in self.owners.items() if v == "alive")
        if leaked:
            raise SemanticError(f"owned allocation(s) not released in {fn_name}: {', '.join(leaked)}")

    def merge(self, left: "_OwnedState", right: "_OwnedState"):
        merged: dict[str, str] = {}
        keys = set(left.owners) | set(right.owners)
        for k in keys:
            lv = left.owners.get(k)
            rv = right.owners.get(k)
            if lv == rv:
                merged[k] = lv
            elif "alive" in {lv, rv}:
                # Conservative: if either branch keeps ownership alive, require explicit cleanup later.
                merged[k] = "alive"
            elif "freed" in {lv, rv}:
                merged[k] = "freed"
            else:
                merged[k] = "moved"
        self.owners = merged

    def _require_alive(self, name: str):
        st = self.owners.get(name)
        if st == "freed":
            raise SemanticError(f"use-after-free of {name}")
        if st == "moved":
            raise SemanticError(f"use-after-move of {name}")

    def _require_reassigned_after_drop(self, name: str):
        st = self.owners.get(name)
        if st == "alive":
            raise SemanticError(f"reassignment would leak owned allocation in {name}; free or move it first")


def analyze(prog: Program):
    fns = {f.name: f for f in prog.items if isinstance(f, FnDecl)}
    if "main" not in fns:
        raise SemanticError("missing main()")
    for fn in fns.values():
        symbols = {n: t for n, t in fn.params}
        owned = _OwnedState()
        for st in fn.body:
            _check_stmt(st, symbols, fns, owned)
        owned.check_no_live_leaks(fn.name)


def _check_stmt(st, symbols, fns, owned: _OwnedState):
    if isinstance(st, LetStmt):
        symbols[st.name] = _infer(st.expr, symbols, fns, owned)
        if isinstance(st.expr, Name):
            owned.assign_name(st.name, st.expr.value)
        if _is_alloc_call(st.expr):
            owned.track_alloc(st.name)
    elif isinstance(st, AssignStmt):
        _infer(st.expr, symbols, fns, owned)
        if isinstance(st.target, Name) and isinstance(st.expr, Name):
            owned.assign_name(st.target.value, st.expr.value)
        elif isinstance(st.target, Name):
            owned._require_reassigned_after_drop(st.target.value)
    elif isinstance(st, ReturnStmt):
        if st.expr:
            if isinstance(st.expr, Name):
                owned.invalidate(st.expr.value)
            _infer(st.expr, symbols, fns, owned)
    elif isinstance(st, IfStmt):
        _infer(st.cond, symbols, fns, owned)
        then_owned = owned.copy()
        for s in st.then_body:
            _check_stmt(s, symbols.copy(), fns, then_owned)
        else_owned = owned.copy()
        for s in st.else_body:
            _check_stmt(s, symbols.copy(), fns, else_owned)
        owned.merge(then_owned, else_owned)
    elif isinstance(st, WhileStmt):
        _infer(st.cond, symbols, fns, owned)
        loop_owned = owned.copy()
        for s in st.body:
            _check_stmt(s, symbols.copy(), fns, loop_owned)
        owned.merge(owned, loop_owned)
    elif isinstance(st, ForStmt):
        loop_owned = owned.copy()
        for s in st.body:
            _check_stmt(s, symbols.copy(), fns, loop_owned)
        owned.merge(owned, loop_owned)
    elif isinstance(st, ExprStmt):
        _infer(st.expr, symbols, fns, owned)
        if _is_free_call(st.expr):
            ptr = st.expr.args[0]
            if not isinstance(ptr, Name):
                raise SemanticError("free() expects a named owner")
            owned.free(ptr.value)


def _infer(e, symbols, fns, owned: _OwnedState | None = None):
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
        if owned is not None:
            owned.check_use(e.value)
        return symbols.get(e.value, "Any")
    if isinstance(e, Unary):
        return _infer(e.expr, symbols, fns, owned)
    if isinstance(e, Binary):
        _infer(e.left, symbols, fns, owned)
        _infer(e.right, symbols, fns, owned)
        return "Int"
    if isinstance(e, Call):
        fn_name = e.fn.value if isinstance(e.fn, Name) else None
        if fn_name and fn_name in fns:
            for a in e.args:
                _infer(a, symbols, fns, owned)
            return fns[fn_name].ret
        if fn_name and fn_name in BUILTINS:
            for a in e.args:
                _infer(a, symbols, fns, owned)
            if fn_name in {"len", "arg"}:
                return "Int"
            if fn_name in {"spawn", "join", "alloc", "free"}:
                return "Int"
            return "Any"
        raise SemanticError(f"undefined function {fn_name or e.fn}")
    if isinstance(e, IndexExpr):
        _infer(e.obj, symbols, fns, owned)
        _infer(e.index, symbols, fns, owned)
        return "Any"
    if isinstance(e, FieldExpr):
        _infer(e.obj, symbols, fns, owned)
        return "Any"
    if isinstance(e, ArrayLit):
        for el in e.elements:
            _infer(el, symbols, fns, owned)
        return "Any"
    return "Any"


def _is_alloc_call(expr):
    return isinstance(expr, Call) and isinstance(expr.fn, Name) and expr.fn.value == "alloc"


def _is_free_call(expr):
    return isinstance(expr, Call) and isinstance(expr.fn, Name) and expr.fn.value == "free" and len(expr.args) == 1
