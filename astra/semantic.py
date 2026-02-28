from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from astra.ast import *


class SemanticError(Exception):
    pass


def _diag(filename: str, line: int, col: int, msg: str) -> str:
    return f"SEM {filename}:{line}:{col}: {msg}"


INT_TYPES = {"i8", "u8", "i16", "u16", "i32", "u32", "i64", "u64", "i128", "u128", "isize", "usize"}
FLOAT_TYPES = {"f32", "f64"}
NUMERIC_TYPES = {"Int", "Float", "Any"} | INT_TYPES | FLOAT_TYPES
PRIMITIVES = {"Int", "Float", "String", "Bool", "Any", "Nil", "Void"} | INT_TYPES | FLOAT_TYPES


@dataclass
class BuiltinSig:
    args: list[str] | None
    ret: str


BUILTIN_SIGS: dict[str, BuiltinSig] = {
    "print": BuiltinSig(["Any"], "Int"),
    "len": BuiltinSig(["Any"], "Int"),
    "read_file": BuiltinSig(["String"], "String"),
    "write_file": BuiltinSig(["String", "String"], "Int"),
    "args": BuiltinSig([], "Any"),
    "arg": BuiltinSig(["Int"], "String"),
    "spawn": BuiltinSig(None, "Int"),
    "join": BuiltinSig(["Int"], "Any"),
    "alloc": BuiltinSig(["Int"], "Int"),
    "free": BuiltinSig(["Int"], "Int"),
    "await_result": BuiltinSig(["Any"], "Any"),
    "list_new": BuiltinSig([], "Any"),
    "list_push": BuiltinSig(["Any", "Any"], "Int"),
    "list_get": BuiltinSig(["Any", "Int"], "Any"),
    "list_set": BuiltinSig(["Any", "Int", "Any"], "Int"),
    "list_len": BuiltinSig(["Any"], "Int"),
    "map_new": BuiltinSig([], "Any"),
    "map_has": BuiltinSig(["Any", "Any"], "Bool"),
    "map_get": BuiltinSig(["Any", "Any"], "Any"),
    "map_set": BuiltinSig(["Any", "Any", "Any"], "Int"),
    "file_exists": BuiltinSig(["String"], "Bool"),
    "file_remove": BuiltinSig(["String"], "Int"),
    "tcp_connect": BuiltinSig(["String"], "Int"),
    "tcp_send": BuiltinSig(["Int", "String"], "Int"),
    "tcp_recv": BuiltinSig(["Int", "Int"], "String"),
    "tcp_close": BuiltinSig(["Int"], "Int"),
    "to_json": BuiltinSig(["Any"], "String"),
    "from_json": BuiltinSig(["String"], "Any"),
    "sha256": BuiltinSig(["String"], "String"),
    "hmac_sha256": BuiltinSig(["String", "String"], "String"),
    "proc_exit": BuiltinSig(["Int"], "Int"),
    "env_get": BuiltinSig(["String"], "String"),
    "cwd": BuiltinSig([], "String"),
    "proc_run": BuiltinSig(["String"], "Int"),
    "now_unix": BuiltinSig([], "Int"),
    "monotonic_ms": BuiltinSig([], "Int"),
    "sleep_ms": BuiltinSig(["Int"], "Int"),
}

for _name, _sig in list(BUILTIN_SIGS.items()):
    if _name.startswith("__"):
        continue
    if _name in {"print", "len", "read_file", "write_file", "args", "arg", "spawn", "join", "alloc", "free", "await_result"}:
        continue
    BUILTIN_SIGS[f"__{_name}"] = _sig


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

    def check_no_live_leaks(self, fn_name: str, filename: str, line: int, col: int):
        leaked = sorted(k for k, v in self.owners.items() if v == "alive")
        if leaked:
            raise SemanticError(_diag(filename, line, col, f"owned allocation(s) not released in {fn_name}: {', '.join(leaked)}"))

    def merge(self, left: "_OwnedState", right: "_OwnedState"):
        merged: dict[str, str] = {}
        keys = set(left.owners) | set(right.owners)
        for k in keys:
            lv = left.owners.get(k)
            rv = right.owners.get(k)
            if lv == rv:
                merged[k] = lv
            elif "alive" in {lv, rv}:
                merged[k] = "alive"
            elif "freed" in {lv, rv}:
                merged[k] = "freed"
            else:
                merged[k] = "moved"
        self.owners = merged

    def _require_alive(self, name: str):
        st = self.owners.get(name)
        if st == "freed":
            raise SemanticError(f"SEM <input>:1:1: use-after-free of {name}")
        if st == "moved":
            raise SemanticError(f"SEM <input>:1:1: use-after-move of {name}")

    def _require_reassigned_after_drop(self, name: str):
        st = self.owners.get(name)
        if st == "alive":
            raise SemanticError(f"SEM <input>:1:1: reassignment would leak owned allocation in {name}; free or move it first")


def _same_type(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    if expected == "Any" or actual == "Any":
        return True
    if expected in {"Float"} | FLOAT_TYPES and actual in {"Int"} | INT_TYPES:
        return True
    if expected == "Int" and actual in INT_TYPES:
        return True
    if actual == "Int" and expected in INT_TYPES:
        return True
    return False


def _require_type(filename: str, line: int, col: int, expected: str, actual: str, what: str):
    if not _same_type(expected, actual):
        raise SemanticError(_diag(filename, line, col, f"type mismatch for {what}: expected {expected}, got {actual}"))


def _resolve_import(path: list[str], filename: str, line: int, col: int):
    root = Path(__file__).resolve().parent.parent
    if not path:
        raise SemanticError(_diag(filename, line, col, "empty import path"))
    if path[0] == "stdlib":
        mod = root / "stdlib" / f"{path[-1]}.astra"
    else:
        base = Path(filename).resolve().parent if filename != "<input>" else root
        mod = base / f"{'/'.join(path)}.astra"
    if not mod.exists():
        raise SemanticError(_diag(filename, line, col, f"cannot resolve import {'::'.join(path)}"))


def _lookup(name: str, scopes: list[dict[str, str]]) -> str | None:
    for scope in reversed(scopes):
        if name in scope:
            return scope[name]
    return None


def _assign(name: str, typ: str, scopes: list[dict[str, str]], filename: str, line: int, col: int):
    for scope in reversed(scopes):
        if name in scope:
            scope[name] = typ
            return
    raise SemanticError(_diag(filename, line, col, f"assignment to undefined name {name}"))


def _lookup_fixed(name: str, fixed_scopes: list[dict[str, bool]]) -> bool | None:
    for scope in reversed(fixed_scopes):
        if name in scope:
            return scope[name]
    return None


def _is_typevar(name: str, known_types: set[str]) -> bool:
    if name in known_types:
        return False
    if any(ch in name for ch in "<>[]&(), "):
        return False
    return bool(name)


def _specialization_score(
    decl: FnDecl | ExternFnDecl,
    arg_types: list[str],
    known_types: set[str],
) -> tuple[int, int, int, int] | None:
    if len(decl.params) != len(arg_types):
        return None
    type_vars = set(getattr(decl, "generics", []))
    for _, pty in decl.params:
        if _is_typevar(pty, known_types):
            type_vars.add(pty)
    bindings: dict[str, str] = {}
    exact = 0
    constrained = 0
    wildcards = 0
    for (_, pty), aty in zip(decl.params, arg_types):
        if pty in type_vars:
            bound = bindings.get(pty)
            if bound is None:
                bindings[pty] = aty
            elif not _same_type(bound, aty):
                return None
            wildcards += 1
            continue
        if pty == "Any":
            wildcards += 1
            continue
        if not _same_type(pty, aty):
            return None
        constrained += 1
        if pty == aty:
            exact += 1
    impl_bonus = 1 if getattr(decl, "is_impl", False) else 0
    return (exact, constrained, -wildcards, impl_bonus)


def _choose_impl(
    name: str,
    decls: list[FnDecl | ExternFnDecl],
    arg_types: list[str],
    known_types: set[str],
    filename: str,
    line: int,
    col: int,
) -> FnDecl | ExternFnDecl:
    ranked: list[tuple[tuple[int, int, int, int], FnDecl | ExternFnDecl]] = []
    for d in decls:
        sc = _specialization_score(d, arg_types, known_types)
        if sc is not None:
            ranked.append((sc, d))
    if not ranked:
        raise SemanticError(_diag(filename, line, col, f"no matching impl for {name}({', '.join(arg_types)})"))
    ranked.sort(key=lambda x: x[0], reverse=True)
    best_score = ranked[0][0]
    best = [d for s, d in ranked if s == best_score]
    if len(best) > 1:
        raise SemanticError(_diag(filename, line, col, f"ambiguous impl for {name}({', '.join(arg_types)})"))
    return best[0]


def analyze(prog: Program, filename: str = "<input>", freestanding: bool = False):
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]] = {}
    structs: dict[str, StructDecl] = {}
    enums: dict[str, EnumDecl] = {}
    for item in prog.items:
        if isinstance(item, ImportDecl):
            _resolve_import(item.path, filename, item.line, item.col)
            continue
        if isinstance(item, StructDecl):
            structs[item.name] = item
            continue
        if isinstance(item, EnumDecl):
            enums[item.name] = item
            continue
        if isinstance(item, (FnDecl, ExternFnDecl)):
            fn_groups.setdefault(item.name, []).append(item)

    for name, decls in fn_groups.items():
        if len(decls) == 1 and not (isinstance(decls[0], FnDecl) and decls[0].is_impl):
            if isinstance(decls[0], FnDecl):
                decls[0].symbol = name
            continue
        for i, d in enumerate(decls):
            if isinstance(d, FnDecl):
                d.symbol = f"{name}__impl{i}"

    if not freestanding:
        mains = [d for d in fn_groups.get("main", []) if isinstance(d, FnDecl)]
        if not mains:
            raise SemanticError(_diag(filename, 1, 1, "missing main()"))
        if len(mains) != 1:
            raise SemanticError(_diag(filename, mains[0].line, mains[0].col, "main() must have a single unambiguous impl"))
        if mains[0].is_impl:
            raise SemanticError(_diag(filename, mains[0].line, mains[0].col, "main() cannot be declared with impl"))

    for decls in fn_groups.values():
        for fn in decls:
            if isinstance(fn, ExternFnDecl):
                continue
            _analyze_fn(fn, fn_groups, structs, enums, filename)


def _analyze_fn(
    fn: FnDecl,
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    filename: str,
):
    scopes: list[dict[str, str]] = [{n: t for n, t in fn.params}]
    fixed_scopes: list[dict[str, bool]] = [{n: False for n, _ in fn.params}]
    owned = _OwnedState()
    for st in fn.body:
        _check_stmt(st, scopes, fixed_scopes, fn_groups, structs, enums, fn.ret, owned, filename, fn.name, 0)
    owned.check_no_live_leaks(fn.name, filename, fn.line, fn.col)


def _check_stmt(
    st,
    scopes: list[dict[str, str]],
    fixed_scopes: list[dict[str, bool]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    fn_ret: str,
    owned: _OwnedState,
    filename: str,
    fn_name: str,
    loop_depth: int,
):
    if isinstance(st, LetStmt):
        ty = _infer(st.expr, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        if st.type_name is not None:
            _require_type(filename, st.line, st.col, st.type_name, ty, st.name)
            ty = st.type_name
        scopes[-1][st.name] = ty
        fixed_scopes[-1][st.name] = st.fixed
        if isinstance(st.expr, Name):
            owned.assign_name(st.name, st.expr.value)
        if _is_alloc_call(st.expr):
            owned.track_alloc(st.name)
        return
    if isinstance(st, AssignStmt):
        rhs = _infer(st.expr, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        if isinstance(st.target, Name):
            is_fixed = _lookup_fixed(st.target.value, fixed_scopes)
            if is_fixed is None:
                raise SemanticError(_diag(filename, st.line, st.col, f"assignment to undefined name {st.target.value}"))
            if is_fixed:
                raise SemanticError(_diag(filename, st.line, st.col, f"cannot assign to fixed binding {st.target.value}"))
            lhs = _lookup(st.target.value, scopes)
            if lhs is None:
                raise SemanticError(_diag(filename, st.line, st.col, f"assignment to undefined name {st.target.value}"))
            _require_type(filename, st.line, st.col, lhs, rhs, st.target.value)
            if isinstance(st.expr, Name):
                owned.assign_name(st.target.value, st.expr.value)
            else:
                owned._require_reassigned_after_drop(st.target.value)
            _assign(st.target.value, lhs, scopes, filename, st.line, st.col)
            return
        _infer(st.target, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        return
    if isinstance(st, ReturnStmt):
        expr_ty = "Void" if st.expr is None else _infer(st.expr, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        _require_type(filename, st.line, st.col, fn_ret, expr_ty, "return")
        if isinstance(st.expr, Name):
            owned.invalidate(st.expr.value)
        return
    if isinstance(st, BreakStmt):
        if loop_depth <= 0:
            raise SemanticError(_diag(filename, st.line, st.col, "break used outside loop"))
        return
    if isinstance(st, ContinueStmt):
        if loop_depth <= 0:
            raise SemanticError(_diag(filename, st.line, st.col, "continue used outside loop"))
        return
    if isinstance(st, DeferStmt):
        _infer(st.expr, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        return
    if isinstance(st, ComptimeStmt):
        for inner in st.body:
            _check_stmt(inner, scopes, fixed_scopes, fn_groups, structs, enums, fn_ret, owned, filename, fn_name, loop_depth)
        return
    if isinstance(st, IfStmt):
        cond_ty = _infer(st.cond, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        _require_type(filename, st.line, st.col, "Bool", cond_ty, "if condition")
        then_owned = owned.copy()
        then_scopes = scopes + [{}]
        then_fixed_scopes = fixed_scopes + [{}]
        for s in st.then_body:
            _check_stmt(s, then_scopes, then_fixed_scopes, fn_groups, structs, enums, fn_ret, then_owned, filename, fn_name, loop_depth)
        else_owned = owned.copy()
        else_scopes = scopes + [{}]
        else_fixed_scopes = fixed_scopes + [{}]
        for s in st.else_body:
            _check_stmt(s, else_scopes, else_fixed_scopes, fn_groups, structs, enums, fn_ret, else_owned, filename, fn_name, loop_depth)
        owned.merge(then_owned, else_owned)
        return
    if isinstance(st, WhileStmt):
        cond_ty = _infer(st.cond, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        _require_type(filename, st.line, st.col, "Bool", cond_ty, "while condition")
        loop_owned = owned.copy()
        loop_scopes = scopes + [{}]
        loop_fixed_scopes = fixed_scopes + [{}]
        for s in st.body:
            _check_stmt(s, loop_scopes, loop_fixed_scopes, fn_groups, structs, enums, fn_ret, loop_owned, filename, fn_name, loop_depth + 1)
        owned.merge(owned, loop_owned)
        return
    if isinstance(st, ForStmt):
        loop_scopes = scopes + [{}]
        loop_fixed_scopes = fixed_scopes + [{}]
        loop_owned = owned.copy()
        if st.init is not None:
            if isinstance(st.init, LetStmt):
                _check_stmt(st.init, loop_scopes, loop_fixed_scopes, fn_groups, structs, enums, fn_ret, loop_owned, filename, fn_name, loop_depth + 1)
            else:
                _infer(st.init, loop_scopes, fn_groups, structs, enums, loop_owned, filename, fn_name)
        if st.cond is not None:
            cond_ty = _infer(st.cond, loop_scopes, fn_groups, structs, enums, loop_owned, filename, fn_name)
            _require_type(filename, st.line, st.col, "Bool", cond_ty, "for condition")
        if st.step is not None:
            if isinstance(st.step, AssignStmt):
                _check_stmt(st.step, loop_scopes, loop_fixed_scopes, fn_groups, structs, enums, fn_ret, loop_owned, filename, fn_name, loop_depth + 1)
            else:
                _infer(st.step, loop_scopes, fn_groups, structs, enums, loop_owned, filename, fn_name)
        for s in st.body:
            _check_stmt(s, loop_scopes, loop_fixed_scopes, fn_groups, structs, enums, fn_ret, loop_owned, filename, fn_name, loop_depth + 1)
        owned.merge(owned, loop_owned)
        return
    if isinstance(st, MatchStmt):
        subject_ty = _infer(st.expr, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        seen_bool: set[bool] = set()
        for pat, body in st.arms:
            pty = _infer(pat, scopes, fn_groups, structs, enums, owned, filename, fn_name)
            if subject_ty != "Any":
                _require_type(filename, st.line, st.col, subject_ty, pty, "match pattern")
            if isinstance(pat, BoolLit):
                seen_bool.add(pat.value)
            arm_scopes = scopes + [{}]
            arm_fixed_scopes = fixed_scopes + [{}]
            for s in body:
                _check_stmt(s, arm_scopes, arm_fixed_scopes, fn_groups, structs, enums, fn_ret, owned.copy(), filename, fn_name, loop_depth)
        if subject_ty == "Bool" and seen_bool != {True, False}:
            raise SemanticError(_diag(filename, st.line, st.col, "non-exhaustive match for Bool"))
        return
    if isinstance(st, ExprStmt):
        _infer(st.expr, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        if _is_free_call(st.expr):
            ptr = st.expr.args[0]
            if not isinstance(ptr, Name):
                raise SemanticError(_diag(filename, st.line, st.col, "free() expects a named owner"))
            owned.free(ptr.value)
        return


def _infer(
    e,
    scopes: list[dict[str, str]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    owned: _OwnedState | None,
    filename: str,
    fn_name: str,
):
    if isinstance(e, BoolLit):
        return "Bool"
    if isinstance(e, NilLit):
        return "Nil"
    if isinstance(e, Literal):
        if isinstance(e.value, bool):
            return "Bool"
        if isinstance(e.value, int):
            return "Int"
        if isinstance(e.value, float):
            return "Float"
        return "String"
    if isinstance(e, Name):
        local = _lookup(e.value, scopes)
        if local is not None:
            if owned is not None:
                owned.check_use(e.value)
            return local
        if e.value in fn_groups:
            if len(fn_groups[e.value]) > 1:
                raise SemanticError(_diag(filename, e.line, e.col, f"ambiguous function reference {e.value}; call it with typed args"))
            return "Any"
        if e.value in structs or e.value in enums or e.value in BUILTIN_SIGS:
            return "Any"
        raise SemanticError(_diag(filename, e.line, e.col, f"undefined name {e.value}"))
    if isinstance(e, AwaitExpr):
        return _infer(e.expr, scopes, fn_groups, structs, enums, owned, filename, fn_name)
    if isinstance(e, Unary):
        inner = _infer(e.expr, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        if e.op == "!":
            _require_type(filename, e.line, e.col, "Bool", inner, "unary !")
            return "Bool"
        if e.op == "-":
            if inner not in NUMERIC_TYPES:
                raise SemanticError(_diag(filename, e.line, e.col, f"unary - expects number, got {inner}"))
            return inner
        return inner
    if isinstance(e, Binary):
        l = _infer(e.left, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        r = _infer(e.right, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        if e.op in {"+", "-", "*", "/", "%"}:
            if l in {"String", "Any"} or r in {"String", "Any"}:
                if e.op == "+" and (l == "String" or r == "String"):
                    return "String"
            if l not in NUMERIC_TYPES or r not in NUMERIC_TYPES:
                raise SemanticError(_diag(filename, e.line, e.col, f"numeric operator {e.op} expects numbers"))
            if l in {"Float"} | FLOAT_TYPES or r in {"Float"} | FLOAT_TYPES:
                return "Float"
            return "Int"
        if e.op in {"==", "!=", "<", "<=", ">", ">="}:
            return "Bool"
        if e.op in {"&&", "||"}:
            _require_type(filename, e.line, e.col, "Bool", l, f"{e.op} left operand")
            _require_type(filename, e.line, e.col, "Bool", r, f"{e.op} right operand")
            return "Bool"
        if e.op == "??":
            if l == "Nil":
                return r
            if r == "Nil":
                return l
            if _same_type(l, r):
                return l
            return "Any"
        return "Any"
    if isinstance(e, Call):
        return _infer_call(e, scopes, fn_groups, structs, enums, owned, filename, fn_name)
    if isinstance(e, IndexExpr):
        _infer(e.obj, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        idx_ty = _infer(e.index, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        _require_type(filename, e.line, e.col, "Int", idx_ty, "index")
        return "Any"
    if isinstance(e, FieldExpr):
        obj_ty = _infer(e.obj, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        if obj_ty in structs:
            for fname, fty in structs[obj_ty].fields:
                if fname == e.field:
                    return fty
        return "Any"
    if isinstance(e, ArrayLit):
        for el in e.elements:
            _infer(el, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        return "Any"
    return "Any"


def _infer_call(
    e: Call,
    scopes: list[dict[str, str]],
    fn_groups: dict[str, list[FnDecl | ExternFnDecl]],
    structs: dict[str, StructDecl],
    enums: dict[str, EnumDecl],
    owned: _OwnedState | None,
    filename: str,
    fn_name: str,
) -> str:
    arg_types = [_infer(a, scopes, fn_groups, structs, enums, owned, filename, fn_name) for a in e.args]
    if isinstance(e.fn, Name):
        name = e.fn.value
        if name in fn_groups:
            known_types = set(PRIMITIVES) | set(structs.keys()) | set(enums.keys())
            decl = _choose_impl(name, fn_groups[name], arg_types, known_types, filename, e.line, e.col)
            if len(e.args) != len(decl.params):
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects {len(decl.params)} args, got {len(e.args)}"))
            for i, ((_, pty), arg) in enumerate(zip(decl.params, e.args)):
                aty = _infer(arg, scopes, fn_groups, structs, enums, owned, filename, fn_name)
                if not _is_typevar(pty, known_types):
                    _require_type(filename, arg.line, arg.col, pty, aty, f"arg {i} for {name}")
            if isinstance(decl, FnDecl):
                e.resolved_name = decl.symbol or decl.name
            return decl.ret
        if name in structs:
            fields = structs[name].fields
            if len(e.args) != len(fields):
                raise SemanticError(_diag(filename, e.line, e.col, f"struct {name} expects {len(fields)} fields, got {len(e.args)}"))
            for (_, fty), arg in zip(fields, e.args):
                aty = _infer(arg, scopes, fn_groups, structs, enums, owned, filename, fn_name)
                _require_type(filename, arg.line, arg.col, fty, aty, f"struct field for {name}")
            return name
        sig = BUILTIN_SIGS.get(name)
        if sig is not None:
            if sig.args is not None and len(e.args) != len(sig.args):
                raise SemanticError(_diag(filename, e.line, e.col, f"{name} expects {len(sig.args)} args, got {len(e.args)}"))
            if sig.args is not None:
                for i, (expected, arg) in enumerate(zip(sig.args, e.args)):
                    aty = _infer(arg, scopes, fn_groups, structs, enums, owned, filename, fn_name)
                    _require_type(filename, arg.line, arg.col, expected, aty, f"arg {i} for {name}")
            return sig.ret
        raise SemanticError(_diag(filename, e.line, e.col, f"undefined function {name}"))
    if isinstance(e.fn, FieldExpr):
        _infer(e.fn.obj, scopes, fn_groups, structs, enums, owned, filename, fn_name)
        return "Any"
    raise SemanticError(_diag(filename, e.line, e.col, f"unsupported callee {e.fn}"))


def _is_alloc_call(expr):
    return isinstance(expr, Call) and isinstance(expr.fn, Name) and expr.fn.value == "alloc"


def _is_free_call(expr):
    return isinstance(expr, Call) and isinstance(expr.fn, Name) and expr.fn.value == "free" and len(expr.args) == 1
