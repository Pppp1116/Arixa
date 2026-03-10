"""LLVM IR backend code generation for Astra programs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra.ast import *
from astra.codegen import CodegenError
from astra.for_lowering import lower_for_loops
from astra.int_types import parse_int_type_name
from astra.layout import LayoutError, layout_of_struct, layout_of_type
from astra.semantic import analyze

try:
    from llvmlite import binding, ir
except Exception:  # pragma: no cover - handled at runtime if llvmlite is unavailable
    binding = None
    ir = None


_LLVM_INIT_DONE = False


@dataclass(frozen=True)
class _FnSig:
    name: str
    params: list[str]
    ret: str
    extern: bool = False
    variadic: bool = False
    link_libs: tuple[str, ...] = ()


@dataclass
class _StructInfo:
    decl: StructDecl
    ty: ir.Type
    field_index: dict[str, int]
    field_types: list[str]
    packed: bool = False
    storage_size: int = 0
    field_bit_offsets: dict[str, int] = field(default_factory=dict)
    field_bits: dict[str, int] = field(default_factory=dict)


@dataclass
class _Value:
    value: ir.Value
    ty: str
    str_len: int | None = None


@dataclass
class _FnState:
    fn_name: str
    fn_ir: ir.Function
    builder: ir.IRBuilder
    ret_type: str
    ret_alloca: ir.Value | None
    epilogue_block: ir.Block
    vars: dict[str, ir.Value] = field(default_factory=dict)
    var_types: dict[str, str] = field(default_factory=dict)
    loop_stack: list[tuple[ir.Block, ir.Block]] = field(default_factory=list)
    stack_promotion_bindings: set[str] = field(default_factory=set)
    stack_alloc_depth: int = 0


@dataclass
class _ModuleCtx:
    module: ir.Module
    triple: str
    freestanding: bool
    structs: dict[str, _StructInfo]
    struct_decls: dict[str, StructDecl]
    slice_header_ty: ir.LiteralStructType
    fn_sigs: dict[str, _FnSig]
    fn_map: dict[str, ir.Function]
    string_globals: dict[str, ir.GlobalVariable]
    ffi_libs: set[str]
    layout_cache: dict[str, Any]
    monomorph_aliases: dict[str, str]


_FREESTANDING_HEAP_BYTES = 8 * 1024 * 1024


def _diag(node: Any, msg: str) -> str:
    line = getattr(node, "line", 0)
    col = getattr(node, "col", 0)
    return f"CODEGEN <input>:{line}:{col}: {msg}"


def _ensure_llvm_available() -> None:
    if binding is None or ir is None:
        raise CodegenError("CODEGEN <input>:1:1: llvmlite is required for LLVM backend; install with `pip install llvmlite`")


def _init_llvm_once() -> None:
    global _LLVM_INIT_DONE
    if _LLVM_INIT_DONE:
        return
    _ensure_llvm_available()
    try:
        binding.initialize_native_target()
        binding.initialize_native_asmprinter()
    except RuntimeError:
        # Newer llvmlite versions auto-initialize.
        pass
    _LLVM_INIT_DONE = True


def _canonical_type(typ: Any) -> str:
    t = type_text(typ)
    if t == "Bytes":
        return "Vec<u8>"
    if t.startswith("&mut "):
        return f"&mut {_canonical_type(t[5:])}"
    if t.startswith("&"):
        return f"&{_canonical_type(t[1:])}"
    return t


def _is_option_type(typ: str) -> bool:
    t = typ.strip()
    if t.endswith("?") or (t.startswith("Option<") and t.endswith(">")):
        return True
    parts = [p.strip() for p in _split_top_level(t, "|")]
    if len(parts) == 2 and "none" in parts:
        return True
    return False


def _option_inner_type(typ: str) -> str:
    t = typ.strip()
    if t.endswith("?"):
        return t[:-1].strip()
    if t.startswith("Option<") and t.endswith(">"):
        return t[7:-1].strip()
    parts = [p.strip() for p in _split_top_level(t, "|")]
    if len(parts) == 2 and "none" in parts:
        return parts[0] if parts[1] == "none" else parts[1]
    return typ


def _parse_parametric_type(typ: str) -> tuple[str, list[str]] | None:
    text = _canonical_type(typ).strip()
    if "<" not in text or not text.endswith(">"):
        return None
    lt = text.find("<")
    base = text[:lt].strip()
    inner = text[lt + 1 : -1].strip()
    if not base or not inner:
        return None
    args = _split_top_level(inner, ",")
    if not args:
        return None
    return base, args


def _is_result_type(typ: str) -> bool:
    parsed = _parse_parametric_type(typ)
    return parsed is not None and parsed[0] == "Result" and len(parsed[1]) == 2


def _result_inner_types(typ: str) -> tuple[str, str] | None:
    parsed = _parse_parametric_type(typ)
    if parsed is None:
        return None
    base, args = parsed
    if base != "Result" or len(args) != 2:
        return None
    return _canonical_type(args[0]), _canonical_type(args[1])


def _int_info(typ: str) -> tuple[int, bool] | None:
    c = _canonical_type(typ)
    if c in {"Int", "isize"}:
        return 64, True
    if c == "usize":
        return 64, False
    return parse_int_type_name(c)


def _is_float_type(typ: str) -> bool:
    return _canonical_type(typ) in {"Float", "f16", "f32", "f64", "f80", "f128"}


def _is_text_type(typ: str) -> bool:
    return _canonical_type(typ) in {"String", "str", "&str", "&mut str"}


def _split_top_level(text: str, sep: str) -> list[str]:
    out: list[str] = []
    depth_angle = 0
    depth_paren = 0
    depth_bracket = 0
    cur: list[str] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "<":
            depth_angle += 1
        elif ch == ">" and depth_angle > 0:
            depth_angle -= 1
        elif ch == "(":
            depth_paren += 1
        elif ch == ")" and depth_paren > 0:
            depth_paren -= 1
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]" and depth_bracket > 0:
            depth_bracket -= 1
        if (
            text.startswith(sep, i)
            and depth_angle == 0
            and depth_paren == 0
            and depth_bracket == 0
        ):
            out.append("".join(cur).strip())
            cur = []
            i += len(sep)
            continue
        cur.append(ch)
        i += 1
    out.append("".join(cur).strip())
    return out


def _parse_fn_type(typ: str) -> tuple[list[str], str, bool] | None:
    text = _canonical_type(typ)
    unsafe = False
    if text.startswith("unsafe "):
        unsafe = True
        text = text[7:].lstrip()
    if not text.startswith("fn("):
        return None
    depth = 0
    close = -1
    for i, ch in enumerate(text):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                close = i
                break
    if close < 0 or depth != 0:
        return None
    if close + 1 > len(text) or text[close + 1] != " ":
        return None
    params_text = text[3:close].strip()
    ret = text[close + 1:].strip()
    if not ret:
        return None
    if not params_text:
        return [], ret, unsafe
    return _split_top_level(params_text, ","), ret, unsafe


def _is_vec_type(typ: str) -> bool:
    t = _canonical_type(typ)
    return t.startswith("Vec<") and t.endswith(">")


def _vec_inner_type(typ: str) -> str:
    t = _canonical_type(typ)
    return t[4:-1].strip()


def _is_slice_type(typ: str) -> bool:
    t = _canonical_type(typ)
    return t.startswith("[") and t.endswith("]")


def _slice_inner_type(typ: str) -> str:
    t = _canonical_type(typ)
    return t[1:-1].strip()


def _strip_ref_type(typ: str) -> str:
    c = _canonical_type(typ)
    if c.startswith("&mut "):
        return c[5:]
    if c.startswith("&"):
        return c[1:]
    return c


def _query_layout(ctx: _ModuleCtx, typ: str, node: Any):
    c = _canonical_type(typ)
    try:
        return layout_of_type(c, ctx.struct_decls, mode="query", _cache=ctx.layout_cache)
    except LayoutError as err:
        raise CodegenError(_diag(node, str(err))) from err


def _storage_size_align(ctx: _ModuleCtx, typ: str, node: Any) -> tuple[int, int]:
    c = _canonical_type(typ)
    try:
        lay = layout_of_type(c, ctx.struct_decls, mode="query", _cache=ctx.layout_cache)
        return lay.size, lay.align
    except LayoutError:
        llty = _llvm_type(ctx, c)
        if isinstance(llty, ir.IntType):
            sz = max(1, (llty.width + 7) // 8)
            if sz <= 1:
                al = 1
            elif sz <= 2:
                al = 2
            elif sz <= 4:
                al = 4
            elif sz <= 8:
                al = 8
            else:
                al = 16
            return sz, al
        if isinstance(llty, ir.FloatType):
            return 4, 4
        if isinstance(llty, ir.DoubleType):
            return 8, 8
        if isinstance(llty, ir.PointerType):
            return 8, 8
        raise CodegenError(_diag(node, f"cannot determine storage layout for {c}"))


def _iter_expr_children(expr: Any) -> list[Any]:
    if expr is None:
        return []
    if isinstance(expr, (Literal, BoolLit, NilLit, Name)):
        return []
    if isinstance(expr, Unary):
        return [expr.expr]
    if isinstance(expr, Binary):
        return [expr.left, expr.right]
    if isinstance(expr, Call):
        return [expr.fn, *list(expr.args)]
    if isinstance(expr, FieldExpr):
        return [expr.obj]
    if isinstance(expr, IndexExpr):
        return [expr.obj, expr.index]
    if isinstance(expr, ArrayLit):
        return list(expr.elements)
    if isinstance(expr, StructLit):
        return [v for _, v in expr.fields]
    if isinstance(expr, StructLiteral):
        return list(expr.args)
    if isinstance(expr, TypeAnnotated):
        return [expr.expr]
    if isinstance(expr, CastExpr):
        return [expr.expr]
    if isinstance(expr, TryExpr):
        return [expr.expr]
    if isinstance(expr, AwaitExpr):
        return [expr.expr]
    if isinstance(expr, StringInterpolation):
        return list(expr.exprs)
    if isinstance(expr, RangeExpr):
        return [expr.start, expr.end]
    if isinstance(expr, MethodCall):
        return [expr.obj, *list(expr.args)]
    if isinstance(expr, VectorLiteral):
        return list(expr.elements)
    if isinstance(expr, SetLiteral):
        return list(expr.elements)
    if isinstance(expr, MapLiteral):
        out: list[Any] = []
        for k, v in expr.pairs:
            out.append(k)
            out.append(v)
        return out
    if isinstance(expr, IfExpression):
        return [expr.cond, expr.then_expr, expr.else_expr]
    return []


def _expr_contains_name(expr: Any, name: str) -> bool:
    if isinstance(expr, Name):
        return expr.value == name
    for child in _iter_expr_children(expr):
        if _expr_contains_name(child, name):
            return True
    return False


def _expr_contains_borrow_of_name(expr: Any, name: str) -> bool:
    if isinstance(expr, Unary) and expr.op in {"&", "&mut"}:
        return _expr_contains_name(expr.expr, name)
    for child in _iter_expr_children(expr):
        if _expr_contains_borrow_of_name(child, name):
            return True
    return False


def _expr_contains_call_use_of_name(expr: Any, name: str) -> bool:
    if isinstance(expr, Call):
        if _expr_contains_name(expr.fn, name):
            return True
        for arg in expr.args:
            if _expr_contains_name(arg, name):
                return True
    if isinstance(expr, MethodCall):
        if _expr_contains_name(expr.obj, name):
            return True
        for arg in expr.args:
            if _expr_contains_name(arg, name):
                return True
    for child in _iter_expr_children(expr):
        if _expr_contains_call_use_of_name(child, name):
            return True
    return False


def _expr_returns_binding_value(expr: Any, name: str) -> bool:
    if isinstance(expr, Name):
        return expr.value == name
    if isinstance(expr, FieldExpr):
        if isinstance(expr.obj, Name) and expr.obj.value == name:
            return False
        return _expr_returns_binding_value(expr.obj, name)
    if isinstance(expr, IndexExpr):
        if isinstance(expr.obj, Name) and expr.obj.value == name:
            return False
        return _expr_returns_binding_value(expr.obj, name) or _expr_returns_binding_value(expr.index, name)
    for child in _iter_expr_children(expr):
        if _expr_returns_binding_value(child, name):
            return True
    return False


def _expr_may_stack_promotable_alloc(expr: Any, ctx: _ModuleCtx) -> bool:
    if isinstance(expr, (ArrayLit, StructLit)):
        return True
    if isinstance(expr, Call):
        if isinstance(expr.fn, Name):
            callee = expr.fn.value
            base = callee[2:] if callee.startswith("__") else callee
            if callee in ctx.structs:
                return True
            if base in {"vec_new"}:
                return True
        if isinstance(expr.fn, FieldExpr) and isinstance(expr.fn.obj, Name):
            if expr.fn.obj.value == "Result" and expr.fn.field in {"Ok", "Err"}:
                return True
    for child in _iter_expr_children(expr):
        if _expr_may_stack_promotable_alloc(child, ctx):
            return True
    return False


def _collect_stmt_names(stmts: list[Any], let_counts: dict[str, int], assigned_names: set[str]) -> None:
    for st in stmts:
        if isinstance(st, LetStmt):
            let_counts[st.name] = let_counts.get(st.name, 0) + 1
        elif isinstance(st, AssignStmt) and isinstance(st.target, Name):
            assigned_names.add(st.target.value)

        if isinstance(st, IfStmt):
            _collect_stmt_names(st.then_body, let_counts, assigned_names)
            _collect_stmt_names(st.else_body, let_counts, assigned_names)
        elif isinstance(st, WhileStmt):
            _collect_stmt_names(st.body, let_counts, assigned_names)
        elif isinstance(st, IteratorForStmt):
            _collect_stmt_names(st.body, let_counts, assigned_names)
        elif isinstance(st, MatchStmt):
            for _, arm_body in st.arms:
                _collect_stmt_names(arm_body, let_counts, assigned_names)
        elif isinstance(st, UnsafeStmt):
            _collect_stmt_names(st.body, let_counts, assigned_names)
        elif isinstance(st, ComptimeStmt):
            _collect_stmt_names(st.body, let_counts, assigned_names)


def _binding_escapes_in_stmts(stmts: list[Any], name: str, decl_stmt: LetStmt) -> bool:
    for st in stmts:
        if isinstance(st, LetStmt):
            if st is not decl_stmt:
                if _expr_contains_borrow_of_name(st.expr, name) or _expr_contains_call_use_of_name(st.expr, name):
                    return True
                if st.name != name and _expr_contains_name(st.expr, name):
                    return True
            continue

        if isinstance(st, AssignStmt):
            if _expr_contains_borrow_of_name(st.expr, name) or _expr_contains_call_use_of_name(st.expr, name):
                return True
            if isinstance(st.target, Name):
                if st.target.value != name and _expr_contains_name(st.expr, name):
                    return True
            else:
                # Storing the binding into another object may outlive the current scope.
                if _expr_contains_name(st.expr, name):
                    return True
                if _expr_contains_borrow_of_name(st.target, name) or _expr_contains_call_use_of_name(st.target, name):
                    return True
            continue

        if isinstance(st, ReturnStmt):
            if st.expr is not None and (
                _expr_contains_borrow_of_name(st.expr, name)
                or _expr_contains_call_use_of_name(st.expr, name)
                or _expr_returns_binding_value(st.expr, name)
            ):
                return True
            continue

        if isinstance(st, ExprStmt):
            if _expr_contains_borrow_of_name(st.expr, name) or _expr_contains_call_use_of_name(st.expr, name):
                return True
            continue

        if isinstance(st, IfStmt):
            if _expr_contains_borrow_of_name(st.cond, name) or _expr_contains_call_use_of_name(st.cond, name):
                return True
            if _binding_escapes_in_stmts(st.then_body, name, decl_stmt):
                return True
            if _binding_escapes_in_stmts(st.else_body, name, decl_stmt):
                return True
            continue

        if isinstance(st, WhileStmt):
            if _expr_contains_borrow_of_name(st.cond, name) or _expr_contains_call_use_of_name(st.cond, name):
                return True
            if _binding_escapes_in_stmts(st.body, name, decl_stmt):
                return True
            continue

        if isinstance(st, IteratorForStmt):
            if _expr_contains_borrow_of_name(st.iterable, name) or _expr_contains_call_use_of_name(st.iterable, name):
                return True
            if _binding_escapes_in_stmts(st.body, name, decl_stmt):
                return True
            continue

        if isinstance(st, MatchStmt):
            if _expr_contains_borrow_of_name(st.expr, name) or _expr_contains_call_use_of_name(st.expr, name):
                return True
            for _, arm_body in st.arms:
                if _binding_escapes_in_stmts(arm_body, name, decl_stmt):
                    return True
            continue

        if isinstance(st, UnsafeStmt):
            if _binding_escapes_in_stmts(st.body, name, decl_stmt):
                return True
            continue

        if isinstance(st, ComptimeStmt):
            if _binding_escapes_in_stmts(st.body, name, decl_stmt):
                return True
            continue
    return False


def _compute_stack_promotion_bindings(ctx: _ModuleCtx, body_stmts: list[Any]) -> set[str]:
    let_counts: dict[str, int] = {}
    assigned_names: set[str] = set()
    _collect_stmt_names(body_stmts, let_counts, assigned_names)

    candidate_lets: dict[str, LetStmt] = {}

    def _collect_candidates(stmts: list[Any]) -> None:
        for st in stmts:
            if isinstance(st, LetStmt):
                if let_counts.get(st.name, 0) != 1:
                    continue
                if st.name in assigned_names:
                    continue
                if not _expr_may_stack_promotable_alloc(st.expr, ctx):
                    continue
                candidate_lets[st.name] = st
                continue
            if isinstance(st, IfStmt):
                _collect_candidates(st.then_body)
                _collect_candidates(st.else_body)
            elif isinstance(st, WhileStmt):
                _collect_candidates(st.body)
            elif isinstance(st, IteratorForStmt):
                _collect_candidates(st.body)
            elif isinstance(st, MatchStmt):
                for _, arm_body in st.arms:
                    _collect_candidates(arm_body)
            elif isinstance(st, UnsafeStmt):
                _collect_candidates(st.body)
            elif isinstance(st, ComptimeStmt):
                _collect_candidates(st.body)

    _collect_candidates(body_stmts)

    promotable: set[str] = set()
    for name, decl in candidate_lets.items():
        if not _binding_escapes_in_stmts(body_stmts, name, decl):
            promotable.add(name)
    return promotable


def _struct_ptr(ctx: _ModuleCtx, state: _FnState, obj_val: ir.Value, obj_ty: str, sinfo: _StructInfo, node: Any) -> ir.Value:
    ptr = obj_val
    if _canonical_type(obj_ty).startswith("&"):
        if not isinstance(ptr.type, ir.PointerType):
            raise CodegenError(_diag(node, "reference receiver is not pointer-like"))
        ptr = state.builder.load(ptr)
    if not isinstance(ptr.type, ir.PointerType):
        raise CodegenError(_diag(node, "struct receiver is not pointer-like"))
    if ptr.type.pointee != sinfo.ty:
        ptr = state.builder.bitcast(ptr, sinfo.ty.as_pointer())
    return ptr


def _packed_window(sinfo: _StructInfo, field: str, node: Any) -> tuple[int, int, int, int]:
    bit_off = sinfo.field_bit_offsets.get(field)
    bits = sinfo.field_bits.get(field)
    if bit_off is None or bits is None:
        raise CodegenError(_diag(node, f"missing packed layout info for field {field}"))
    if bits <= 0:
        raise CodegenError(_diag(node, f"invalid packed field width {bits} for {field}"))
    storage_size = max(1, sinfo.storage_size)
    byte_off = bit_off // 8
    bit_shift = bit_off % 8
    nbytes = (bit_shift + bits + 7) // 8
    if byte_off + nbytes > storage_size:
        raise CodegenError(_diag(node, f"packed field {field} exceeds storage bounds"))
    return byte_off, bit_shift, bits, nbytes


def _packed_load_bits(ctx: _ModuleCtx, state: _FnState, base_ptr: ir.Value, sinfo: _StructInfo, field: str, node: Any) -> tuple[ir.Value, int, int]:
    b = state.builder
    i8 = ir.IntType(8)
    i64 = ir.IntType(64)
    byte_off, bit_shift, bits, nbytes = _packed_window(sinfo, field, node)
    int_ty = ir.IntType(max(1, nbytes * 8))
    base_i8 = b.bitcast(base_ptr, i8.as_pointer())
    acc = ir.Constant(int_ty, 0)
    for i in range(nbytes):
        p = b.gep(base_i8, [ir.Constant(i64, byte_off + i)])
        by = b.load(p)
        ext = b.zext(by, int_ty)
        if i:
            ext = b.shl(ext, ir.Constant(int_ty, i * 8))
        acc = b.or_(acc, ext)
    shifted = b.lshr(acc, ir.Constant(int_ty, bit_shift))
    mask_v = (1 << bits) - 1 if bits > 0 else 0
    raw = b.and_(shifted, ir.Constant(int_ty, mask_v))
    return raw, bits, bit_shift


def _packed_store_bits(
    ctx: _ModuleCtx,
    state: _FnState,
    base_ptr: ir.Value,
    sinfo: _StructInfo,
    field: str,
    new_bits: ir.Value,
    node: Any,
) -> None:
    b = state.builder
    i8 = ir.IntType(8)
    i64 = ir.IntType(64)
    byte_off, bit_shift, bits, nbytes = _packed_window(sinfo, field, node)
    int_ty = ir.IntType(max(1, nbytes * 8))
    base_i8 = b.bitcast(base_ptr, i8.as_pointer())

    old = ir.Constant(int_ty, 0)
    for i in range(nbytes):
        p = b.gep(base_i8, [ir.Constant(i64, byte_off + i)])
        by = b.load(p)
        ext = b.zext(by, int_ty)
        if i:
            ext = b.shl(ext, ir.Constant(int_ty, i * 8))
        old = b.or_(old, ext)

    if isinstance(new_bits.type, ir.IntType):
        if new_bits.type.width > int_ty.width:
            nb = b.trunc(new_bits, int_ty)
        elif new_bits.type.width < int_ty.width:
            nb = b.zext(new_bits, int_ty)
        else:
            nb = new_bits
    else:
        raise CodegenError(_diag(node, "packed field assignment expects integer value"))

    # Truncate value to field width first
    mask_v = (1 << bits) - 1 if bits > 0 else 0
    truncated_value = b.and_(nb, ir.Constant(int_ty, mask_v))
    
    # Clear destination bits and insert new value
    field_mask = mask_v << bit_shift
    window_bits = nbytes * 8
    full_mask = (1 << window_bits) - 1
    clear_mask = full_mask ^ field_mask
    inserted = b.shl(truncated_value, ir.Constant(int_ty, bit_shift))
    merged = b.or_(b.and_(old, ir.Constant(int_ty, clear_mask)), inserted)

    for i in range(nbytes):
        part = b.lshr(merged, ir.Constant(int_ty, i * 8))
        out_b = b.trunc(part, i8)
        p = b.gep(base_i8, [ir.Constant(i64, byte_off + i)])
        b.store(out_b, p)


def _collect_fn_sigs(prog: Program) -> dict[str, _FnSig]:
    out: dict[str, _FnSig] = {}
    for item in prog.items:
        if isinstance(item, FnDecl):
            name = item.symbol or item.name
            out[name] = _FnSig(
                name=name,
                params=[_canonical_type(typ) for _, typ in item.params],
                ret=_canonical_type(item.ret),
                extern=False,
            )
        elif isinstance(item, ExternFnDecl):
            libs = tuple(item.link_libs or ([item.lib] if item.lib else []))
            out[item.name] = _FnSig(
                name=item.name,
                params=[_canonical_type(typ) for _, typ in item.params],
                ret=_canonical_type(item.ret),
                extern=True,
                variadic=bool(item.is_variadic),
                link_libs=libs,
            )
    return out


def _llvm_type(ctx: _ModuleCtx, typ: str) -> ir.Type:
    c = _canonical_type(typ)
    if c.startswith("*"):
        base = c.lstrip("*")
        depth = len(c) - len(base)
        if base == "u8":
            out_ty: ir.Type = ir.IntType(8).as_pointer()
        else:
            out_ty = ir.IntType(8).as_pointer()
        for _ in range(max(0, depth - 1)):
            out_ty = out_ty.as_pointer()
        return out_ty
    if _is_option_type(c):
        return ir.IntType(8).as_pointer()
    if _is_result_type(c):
        return ir.IntType(8).as_pointer()
    if c == "Bool":
        return ir.IntType(1)
    info = _int_info(c)
    if info is not None:
        bits, _ = info
        return ir.IntType(bits)
    if c == "f16":
        return ir.FloatType()
    if c == "f32":
        return ir.FloatType()
    if c in {"Float", "f64"}:
        return ir.DoubleType()
    if c == "f80":
        # f80 uses software emulation - map to i80 for storage
        return ir.IntType(80)
    if c == "f128":
        # f128 uses software emulation - map to i128 for storage
        return ir.IntType(128)
    if c in {"Void", "Never"}:
        return ir.VoidType()
    if c in ctx.structs:
        return ctx.structs[c].ty.as_pointer()
    if c.startswith("&mut "):
        return _llvm_type(ctx, c[5:]).as_pointer()
    if c.startswith("&"):
        return _llvm_type(ctx, c[1:]).as_pointer()
    if c.startswith("fn("):
        # Parse function type and create proper function pointer type
        parsed = _parse_fn_type(c)
        if parsed:
            param_tys, ret_ty, unsafe = parsed
            param_ll_tys = [_llvm_type(ctx, pt) for pt in param_tys]
            ret_ll_ty = _llvm_type(ctx, ret_ty)
            return ir.FunctionType(ret_ll_ty, param_ll_tys).as_pointer()
        return ir.IntType(8).as_pointer()
    if c in {"String", "str"}:
        return ir.IntType(8).as_pointer()
    if _is_vec_type(c) or _is_slice_type(c):
        return ctx.slice_header_ty.as_pointer()
    return ir.IntType(64)


def _default_value(ctx: _ModuleCtx, typ: str) -> ir.Constant:
    llty = _llvm_type(ctx, typ)
    if isinstance(llty, ir.IntType):
        return ir.Constant(llty, 0)
    if isinstance(llty, ir.FloatType):
        return ir.Constant(llty, 0.0)
    if isinstance(llty, ir.DoubleType):
        return ir.Constant(llty, 0.0)
    if isinstance(llty, ir.PointerType):
        return ir.Constant(llty, None)
    if isinstance(llty, ir.LiteralStructType):
        return ir.Constant(llty, [ir.Constant(t, 0) if isinstance(t, ir.IntType) else ir.Constant(t, None) for t in llty.elements])
    if isinstance(llty, ir.VoidType):
        return ir.Constant(ir.IntType(1), 0)
    raise CodegenError(f"internal: no default value for {typ}")


def _result_storage_ty() -> ir.LiteralStructType:
    return ir.LiteralStructType([ir.IntType(8), ir.IntType(64)], packed=False)


def _emit_result_value(
    ctx: _ModuleCtx,
    state: _FnState,
    result_ty: str,
    *,
    is_ok: bool,
    payload_v: ir.Value,
    payload_ty: str,
    node: Any,
) -> ir.Value:
    parsed = _result_inner_types(result_ty)
    if parsed is None:
        raise CodegenError(_diag(node, f"internal: expected Result<T, E> type, got {result_ty}"))
    _ok_ty, _err_ty = parsed
    payload_any = _coerce_value(ctx, state, payload_v, payload_ty, "Any", node)
    if not (isinstance(payload_any.type, ir.IntType) and payload_any.type.width == 64):
        payload_any = state.builder.bitcast(payload_any, ir.IntType(64))

    i64 = ir.IntType(64)
    mem = _alloc_bytes(ctx, state, ir.Constant(i64, 16), ir.Constant(i64, 8), node, stack_ok=True)
    s_ptr = state.builder.bitcast(mem, _result_storage_ty().as_pointer())
    tag_ptr = state.builder.gep(s_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
    payload_ptr = state.builder.gep(s_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
    state.builder.store(ir.Constant(ir.IntType(8), 1 if is_ok else 0), tag_ptr)
    state.builder.store(payload_any, payload_ptr)

    out_ty = _llvm_type(ctx, result_ty)
    if mem.type != out_ty:
        return state.builder.bitcast(mem, out_ty)
    return mem


def _is_terminated(state: _FnState) -> bool:
    return state.builder.block.terminator is not None


def _is_signed_int(typ: str) -> bool:
    info = _int_info(typ)
    return bool(info[1]) if info is not None else True


def _get_abi_extension_attr(param_ty: str) -> str:
    """Get the appropriate LLVM ABI extension attribute for small integer types."""
    info = _int_info(param_ty)
    if info and info[0] < 64:  # Small integer (< 64 bits)
        return "signext" if info[1] else "zeroext"
    return None


def _apply_abi_attributes_to_call(ctx: _ModuleCtx, call_inst, fn_sig: _FnSig) -> None:
    """Apply proper LLVM ABI attributes to extern function call sites.
    
    Note: In LLVM, ABI attributes are primarily applied to function declarations.
    Call instruction arguments only need attributes when they are values that can
    have attributes (not constants). The LLVM verifier ensures ABI consistency.
    """
    # Apply attributes to arguments that support them (non-constants)
    for i, param_ty in enumerate(fn_sig.params):
        attr = _get_abi_extension_attr(param_ty)
        if attr and i < len(call_inst.args):
            arg = call_inst.args[i]
            # Only add attributes to arguments that support them (not constants)
            if hasattr(arg, 'add_attribute'):
                arg.add_attribute(attr)
    
    # Return value attributes are handled by the function declaration in LLVM
    # Call instructions don't need explicit return attributes


def _apply_abi_attributes_to_extern_fn(ctx: _ModuleCtx, fn_decl: ExternFnDecl, fn_sig: _FnSig, ir_fn: ir.Function) -> None:
    """Apply proper LLVM ABI attributes to extern function parameters and return value."""
    # Apply attributes to parameters
    for i, param_ty in enumerate(fn_sig.params):
        attr = _get_abi_extension_attr(param_ty)
        if attr:
            ir_fn.args[i].add_attribute(attr)
    
    # Apply attribute to return value
    ret_attr = _get_abi_extension_attr(fn_sig.ret)
    if ret_attr:
        ir_fn.return_value.add_attribute(ret_attr)


def _implicit_coerce_value(ctx: _ModuleCtx, state: _FnState, v: ir.Value, from_ty: str, to_ty: str, node: Any) -> ir.Value:
    """Implicit coercion - only allows widening, no precision loss."""
    from_c = _canonical_type(from_ty)
    to_c = _canonical_type(to_ty)
    if from_c == to_c:
        return v
    
    # Check for implicit truncation - should never happen
    lf = _llvm_type(ctx, from_c)
    lt = _llvm_type(ctx, to_c)
    if isinstance(lf, ir.IntType) and isinstance(lt, ir.IntType):
        if lf.width > lt.width:
            raise CodegenError(_diag(node, 
                f"implicit truncation from {from_c} to {to_c} not allowed"))
    
    # For implicit coercion, use the same logic as explicit cast but with stricter checks
    return _explicit_cast_value(ctx, state, v, from_ty, to_ty, node)


def _explicit_cast_value(ctx: _ModuleCtx, state: _FnState, v: ir.Value, from_ty: str, to_ty: str, node: Any) -> ir.Value:
    """Explicit cast - allows narrowing with explicit truncation."""
    from_c = _canonical_type(from_ty)
    to_c = _canonical_type(to_ty)
    if from_c == to_c:
        return v
    b = state.builder
    i64 = ir.IntType(64)
    lf = _llvm_type(ctx, from_c)
    lt = _llvm_type(ctx, to_c)

    if _is_option_type(to_c):
        lt_opt = _llvm_type(ctx, to_c)
        if _is_option_type(from_c):
            if isinstance(v.type, ir.PointerType) and v.type != lt_opt:
                return b.bitcast(v, lt_opt)
            return v
        inner = _option_inner_type(to_c)
        inner_v = _explicit_cast_value(ctx, state, v, from_c, inner, node)
        sz, al = _storage_size_align(ctx, inner, node)
        mem = _alloc_bytes(ctx, state, ir.Constant(i64, sz), ir.Constant(i64, al), node, stack_ok=True)
        inner_ptr = b.bitcast(mem, _llvm_type(ctx, inner).as_pointer())
        b.store(inner_v, inner_ptr)
        if mem.type != lt_opt:
            return b.bitcast(mem, lt_opt)
        return mem

    if from_c == "Any":
        any_v = v
        if not (isinstance(any_v.type, ir.IntType) and any_v.type.width == 64):
            any_v = b.bitcast(any_v, i64)
        if to_c == "Bool":
            fn = _declare_runtime(ctx, "astra_any_to_bool")
            return b.call(fn, [any_v])
        if to_c in {"String", "str"}:
            fn = _declare_runtime(ctx, "astra_any_to_str")
            out = b.call(fn, [any_v])
            lt = _llvm_type(ctx, to_c)
            if isinstance(lt, ir.PointerType) and lt != out.type:
                return b.bitcast(out, lt)
            return out
        if _is_float_type(to_c):
            fn = _declare_runtime(ctx, "astra_any_to_f64")
            out = b.call(fn, [any_v])
            lt = _llvm_type(ctx, to_c)
            if isinstance(lt, ir.FloatType):
                return b.fptrunc(out, lt)
            return out
        lt = _llvm_type(ctx, to_c)
        if isinstance(lt, ir.IntType):
            fn = _declare_runtime(ctx, "astra_any_to_i64")
            raw = b.call(fn, [any_v])
            if lt.width < 64:
                return b.trunc(raw, lt)
            if lt.width > 64:
                if _is_signed_int(to_c):
                    return b.sext(raw, lt)
                return b.zext(raw, lt)
            return raw
        if isinstance(lt, ir.PointerType):
            fn = _declare_runtime(ctx, "astra_any_to_ptr")
            return b.call(fn, [any_v])
        raise CodegenError(_diag(node, f"internal: cannot cast Any to {to_c}"))

    if to_c == "Any":
        if from_c == "Bool":
            in_v = v
            if not (isinstance(in_v.type, ir.IntType) and in_v.type.width == 1):
                in_v = b.trunc(in_v, ir.IntType(1))
            fn = _declare_runtime(ctx, "astra_any_box_bool")
            return b.call(fn, [in_v])
        if from_c in {"String", "str"}:
            in_v = v
            if isinstance(in_v.type, ir.PointerType):
                in_v = b.ptrtoint(in_v, i64)
            fn = _declare_runtime(ctx, "astra_any_box_i64")
            return b.call(fn, [in_v])
        if _is_float_type(from_c):
            in_v = v
            if isinstance(in_v.type, ir.FloatType):
                in_v = b.fpext(in_v, ir.DoubleType())
            elif not isinstance(in_v.type, ir.DoubleType):
                raise CodegenError(_diag(node, f"cannot box non-float value {from_c}"))
            fn = _declare_runtime(ctx, "astra_any_box_f64")
            return b.call(fn, [in_v])
        lf = _llvm_type(ctx, from_c)
        if isinstance(lf, ir.IntType):
            in_v = v
            if lf.width < 64:
                if _is_signed_int(from_c):
                    in_v = b.sext(in_v, i64)
                else:
                    in_v = b.zext(in_v, i64)
            elif lf.width > 64:
                in_v = b.trunc(in_v, i64)
            fn = _declare_runtime(ctx, "astra_any_box_i64")
            return b.call(fn, [in_v])
        if isinstance(lf, ir.PointerType):
            fn = _declare_runtime(ctx, "astra_any_box_i64")
            return b.call(fn, [b.ptrtoint(v, i64)])
        raise CodegenError(_diag(node, f"internal: cannot cast {from_c} to Any"))

    if from_c == "Bool" and isinstance(lt, ir.IntType):
        if lt.width == 1:
            return v
        return b.zext(v, lt)
    if to_c == "Bool" and isinstance(lf, ir.IntType):
        if lf.width == 1:
            return v
        return b.icmp_unsigned("!=", v, ir.Constant(lf, 0))
    if from_c == "Bool" and isinstance(lt, (ir.FloatType, ir.DoubleType)):
        return b.uitofp(v, lt)
    if to_c == "Bool" and isinstance(lf, (ir.FloatType, ir.DoubleType)):
        return b.fcmp_ordered("!=", v, ir.Constant(lf, 0.0))
    if isinstance(lf, ir.IntType) and isinstance(lt, ir.IntType):
        if lf.width > lt.width:
            return b.trunc(v, lt)
        if lf.width < lt.width:
            if _is_signed_int(from_c):
                return b.sext(v, lt)
            return b.zext(v, lt)
        return v
    if isinstance(lf, ir.IntType) and isinstance(lt, (ir.FloatType, ir.DoubleType)):
        if _is_signed_int(from_c):
            return b.sitofp(v, lt)
        return b.uitofp(v, lt)
    if isinstance(lf, (ir.FloatType, ir.DoubleType)) and isinstance(lt, ir.IntType):
        sat = _declare_fptoi_sat_intrinsic(ctx, bits=lt.width, signed=_is_signed_int(to_c), from_ty=lf)
        return b.call(sat, [v])
    if isinstance(lf, ir.FloatType) and isinstance(lt, ir.DoubleType):
        return b.fpext(v, lt)
    if isinstance(lf, ir.DoubleType) and isinstance(lt, ir.FloatType):
        return b.fptrunc(v, lt)
    if isinstance(lf, ir.PointerType) and isinstance(lt, ir.IntType):
        return b.ptrtoint(v, lt)
    if isinstance(lf, ir.IntType) and isinstance(lt, ir.PointerType):
        return b.inttoptr(v, lt)
    if isinstance(lf, ir.PointerType) and isinstance(lt, ir.PointerType):
        return b.bitcast(v, lt)
    raise CodegenError(_diag(node, f"internal: cannot cast {from_c} to {to_c}"))


def _coerce_value(ctx: _ModuleCtx, state: _FnState, v: ir.Value, from_ty: str, to_ty: str, node: Any) -> ir.Value:
    from_c = _canonical_type(from_ty)
    to_c = _canonical_type(to_ty)
    if from_c == to_c:
        # Keep semantic type identity but reconcile backend representation when
        # aliases use pointer-erased values (e.g. Vec headers carried as i8*).
        lt_same = _llvm_type(ctx, to_c)
        if v.type == lt_same:
            return v
        if isinstance(v.type, ir.PointerType) and isinstance(lt_same, ir.PointerType):
            return state.builder.bitcast(v, lt_same)
        return v
    b = state.builder
    i64 = ir.IntType(64)

    if _is_option_type(to_c):
        lt_opt = _llvm_type(ctx, to_c)
        if _is_option_type(from_c):
            if isinstance(v.type, ir.PointerType) and v.type != lt_opt:
                return b.bitcast(v, lt_opt)
            return v
        inner = _option_inner_type(to_c)
        inner_v = _coerce_value(ctx, state, v, from_c, inner, node)
        sz, al = _storage_size_align(ctx, inner, node)
        mem = _alloc_bytes(ctx, state, ir.Constant(i64, sz), ir.Constant(i64, al), node, stack_ok=True)
        inner_ptr = b.bitcast(mem, _llvm_type(ctx, inner).as_pointer())
        b.store(inner_v, inner_ptr)
        if mem.type != lt_opt:
            return b.bitcast(mem, lt_opt)
        return mem

    if from_c == "Any":
        any_v = v
        if not (isinstance(any_v.type, ir.IntType) and any_v.type.width == 64):
            any_v = b.bitcast(any_v, i64)
        if to_c == "Bool":
            fn = _declare_runtime(ctx, "astra_any_to_bool")
            return b.call(fn, [any_v])
        if to_c in {"String", "str"}:
            fn = _declare_runtime(ctx, "astra_any_to_str")
            out = b.call(fn, [any_v])
            lt = _llvm_type(ctx, to_c)
            if isinstance(lt, ir.PointerType) and lt != out.type:
                return b.bitcast(out, lt)
            return out
        if _is_float_type(to_c):
            fn = _declare_runtime(ctx, "astra_any_to_f64")
            out = b.call(fn, [any_v])
            lt = _llvm_type(ctx, to_c)
            if isinstance(lt, ir.FloatType):
                return b.fptrunc(out, lt)
            return out
        lt = _llvm_type(ctx, to_c)
        if isinstance(lt, ir.IntType):
            fn = _declare_runtime(ctx, "astra_any_to_i64")
            raw = b.call(fn, [any_v])
            if lt.width < 64:
                return b.trunc(raw, lt)
            if lt.width > 64:
                if _is_signed_int(to_c):
                    return b.sext(raw, lt)
                return b.zext(raw, lt)
            return raw
        if isinstance(lt, ir.PointerType):
            fn = _declare_runtime(ctx, "astra_any_to_ptr")
            raw = b.call(fn, [any_v])
            return b.inttoptr(raw, lt)
        raise CodegenError(_diag(node, f"cannot coerce Any to {to_c} in LLVM backend"))

    if to_c == "Any":
        lf = _llvm_type(ctx, from_c)
        if from_c == "Bool":
            in_v = v
            if not (isinstance(in_v.type, ir.IntType) and in_v.type.width == 1):
                in_v = b.trunc(in_v, ir.IntType(1))
            fn = _declare_runtime(ctx, "astra_any_box_bool")
            return b.call(fn, [in_v])
        if from_c in {"String", "str"}:
            in_v = v
            if not isinstance(in_v.type, ir.PointerType):
                raise CodegenError(_diag(node, f"cannot box non-pointer string value {from_c}"))
            if in_v.type != ir.IntType(8).as_pointer():
                in_v = b.bitcast(in_v, ir.IntType(8).as_pointer())
            fn = _declare_runtime(ctx, "astra_any_box_str")
            return b.call(fn, [in_v])
        if _is_float_type(from_c):
            in_v = v
            if isinstance(in_v.type, ir.FloatType):
                in_v = b.fpext(in_v, ir.DoubleType())
            elif not isinstance(in_v.type, ir.DoubleType):
                raise CodegenError(_diag(node, f"cannot box non-float value {from_c}"))
            fn = _declare_runtime(ctx, "astra_any_box_f64")
            return b.call(fn, [in_v])
        if isinstance(lf, ir.IntType):
            in_v = v
            if lf.width < 64:
                if _is_signed_int(from_c):
                    in_v = b.sext(in_v, i64)
                else:
                    in_v = b.zext(in_v, i64)
            elif lf.width > 64:
                in_v = b.trunc(in_v, i64)
            fn = _declare_runtime(ctx, "astra_any_box_i64")
            return b.call(fn, [in_v])
        if isinstance(lf, ir.PointerType):
            raw = b.ptrtoint(v, i64)
            fn = _declare_runtime(ctx, "astra_any_box_ptr")
            return b.call(fn, [raw])
        raise CodegenError(_diag(node, f"cannot box {from_c} into Any in LLVM backend"))

    lf = _llvm_type(ctx, from_c)
    lt = _llvm_type(ctx, to_c)
    if lf == lt:
        return v
    if from_c == "Bool" and isinstance(lt, ir.IntType):
        if lt.width == 1:
            return v
        return b.zext(v, lt)
    if to_c == "Bool" and isinstance(lf, ir.IntType):
        if lf.width == 1:
            return v
        return b.icmp_unsigned("!=", v, ir.Constant(lf, 0))
    if from_c == "Bool" and isinstance(lt, (ir.FloatType, ir.DoubleType)):
        return b.uitofp(v, lt)
    if to_c == "Bool" and isinstance(lf, (ir.FloatType, ir.DoubleType)):
        return b.fcmp_ordered("!=", v, ir.Constant(lf, 0.0))
    if isinstance(lf, ir.IntType) and isinstance(lt, ir.IntType):
        if lf.width > lt.width:
            return b.trunc(v, lt)
        if lf.width < lt.width:
            if _is_signed_int(to_c):
                return b.sext(v, lt)
            return b.zext(v, lt)
        return v
    if isinstance(lf, ir.IntType) and isinstance(lt, (ir.FloatType, ir.DoubleType)):
        if _is_signed_int(from_c):
            return b.sitofp(v, lt)
        return b.uitofp(v, lt)
    if isinstance(lf, (ir.FloatType, ir.DoubleType)) and isinstance(lt, ir.IntType):
        sat = _declare_fptoi_sat_intrinsic(ctx, bits=lt.width, signed=_is_signed_int(to_c), from_ty=lf)
        return b.call(sat, [v])
    if isinstance(lf, ir.FloatType) and isinstance(lt, ir.DoubleType):
        return b.fpext(v, lt)
    if isinstance(lf, ir.DoubleType) and isinstance(lt, ir.FloatType):
        return b.fptrunc(v, lt)
    if isinstance(lf, ir.PointerType) and isinstance(lt, ir.IntType):
        return b.ptrtoint(v, lt)
    if isinstance(lf, ir.IntType) and isinstance(lt, ir.PointerType):
        return b.inttoptr(v, lt)
    if isinstance(lf, ir.PointerType) and isinstance(lt, ir.PointerType):
        return b.bitcast(v, lt)
    if isinstance(lt, ir.VoidType):
        return v
    raise CodegenError(_diag(node, f"cannot coerce {from_c} to {to_c} in LLVM backend"))


def _expr_type(state: _FnState, e: Any) -> str:
    t = getattr(e, "inferred_type", None)
    if isinstance(t, str):
        return _canonical_type(t)
    if isinstance(e, BoolLit):
        return "Bool"
    if isinstance(e, Literal):
        if isinstance(e.value, float):
            return "Float"
        if isinstance(e.value, str):
            return "String"
        return "Int"
    if isinstance(e, NilLit):
        return "Option<Any>"
    if isinstance(e, Name):
        # First check if the name has an inferred type (from semantic analyzer)
        inferred = getattr(e, "inferred_type", None)
        if inferred:
            return _canonical_type(inferred)
        # Then check local variables
        if e.value in state.var_types:
            return state.var_types[e.value]
    if isinstance(e, CastExpr):
        return _canonical_type(e.type_name)
    if isinstance(e, TypeAnnotated):
        return _canonical_type(e.type_name)
    if isinstance(e, Unary):
        if e.op in {"&", "&mut"}:
            inner = _expr_type(state, e.expr)
            return f"&mut {inner}" if e.op == "&mut" else f"&{inner}"
        if e.op == "*":
            inner = _expr_type(state, e.expr)
            if inner.startswith("&mut "):
                return _canonical_type(inner[5:])
            if inner.startswith("&"):
                return _canonical_type(inner[1:])
        return _expr_type(state, e.expr)
    if isinstance(e, Binary):
        if e.op in {"==", "!=", "<", "<=", ">", ">=", "&&", "||"}:
            return "Bool"
        if e.op == "??":
            lt = _expr_type(state, e.left)
            return _option_inner_type(lt) if _is_option_type(lt) else _expr_type(state, e.right)
        return _expr_type(state, e.left)
    if isinstance(e, Call):
        if isinstance(e.fn, Name):
            name = e.resolved_name or e.fn.value
            if name in {"print", "__print", "panic", "__panic"}:
                return "Void"
            if name in {
                "countOnes",
                "leadingZeros",
                "trailingZeros",
                "popcnt",
                "clz",
                "ctz",
                "__countOnes",
                "__leadingZeros",
                "__trailingZeros",
                "__popcnt",
                "__clz",
                "__ctz",
            }:
                return "Int"
            if name in {"rotl", "rotr", "__rotl", "__rotr"} and e.args:
                return _expr_type(state, e.args[0])
            if name in {"vec_new", "__vec_new", "vec_from", "__vec_from"}:
                return "Any"
            if name in {"vec_len", "__vec_len", "vec_set", "__vec_set", "vec_push", "__vec_push"}:
                return "Int"
            if name in {"vec_get", "__vec_get"}:
                return "Option<Any>"
        return "Int"
    if isinstance(e, FieldExpr):
        obj_ty = _expr_type(state, e.obj)
        base = obj_ty
        if base.startswith("&mut "):
            base = base[5:]
        elif base.startswith("&"):
            base = base[1:]
        return base
    if isinstance(e, StructLit):
        return _canonical_type(e.name)
    if isinstance(e, AwaitExpr):
        return _expr_type(state, e.expr)
    if isinstance(e, TryExpr):
        src_ty = _expr_type(state, e.expr)
        if _is_option_type(src_ty):
            return _option_inner_type(src_ty)
        parsed = _result_inner_types(src_ty)
        if parsed is not None:
            return parsed[0]
        return "Any"
    return "Int"


def _get_string_global(ctx: _ModuleCtx, text: str) -> ir.GlobalVariable:
    g = ctx.string_globals.get(text)
    if g is not None:
        return g
    data = text.encode("utf-8") + b"\x00"
    arr_ty = ir.ArrayType(ir.IntType(8), len(data))
    idx = len(ctx.string_globals)
    g = ir.GlobalVariable(ctx.module, arr_ty, name=f".str.{idx}")
    g.linkage = "internal"
    g.global_constant = True
    g.initializer = ir.Constant(arr_ty, bytearray(data))
    ctx.string_globals[text] = g
    return g


def _needs_any_runtime(prog: Program) -> bool:
    """Check if Any runtime support is needed."""
    any_usage = getattr(prog, "any_usage", None)
    if any_usage is None:
        return False
    return any_usage.needs_any_runtime()


def _declare_runtime(ctx: _ModuleCtx, name: str) -> ir.Function:
    if name in ctx.fn_map:
        fn = ctx.fn_map[name]
        if isinstance(fn, ir.Function):
            return fn
    
    # Check if Any runtime is needed
    prog = getattr(ctx, 'prog', None)
    if prog and _needs_any_runtime(prog):
        # Any runtime is available
        pass
    elif name.startswith("astra_any_") or name in {"astra_list_new", "astra_map_new", "astra_list_push", "astra_list_get", "astra_list_set", "astra_list_len", "astra_map_has", "astra_map_get", "astra_map_set"}:
        # Any runtime not needed, raise error for Any functions
        raise CodegenError(f"Any runtime function '{name}' used but Any support not required. Use typed containers instead.")
    
    i64 = ir.IntType(64)
    i128 = ir.IntType(128)
    i8p = ir.IntType(8).as_pointer()
    i1 = ir.IntType(1)
    if name == "astra_print_i64":
        fnty = ir.FunctionType(ir.VoidType(), [i64])
    elif name == "astra_print_int":
        fnty = ir.FunctionType(ir.VoidType(), [i64])
    elif name == "astra_print_str":
        fnty = ir.FunctionType(ir.VoidType(), [i8p, i64])
    elif name == "astra_any_box_i64":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_any_box_bool":
        fnty = ir.FunctionType(i64, [i1])
    elif name == "astra_any_box_f64":
        fnty = ir.FunctionType(i64, [ir.DoubleType()])
    elif name == "astra_any_box_str":
        fnty = ir.FunctionType(i64, [i8p])
    elif name == "astra_any_box_ptr":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_any_to_i64":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_any_to_bool":
        fnty = ir.FunctionType(i1, [i64])
    elif name == "astra_any_to_f64":
        fnty = ir.FunctionType(ir.DoubleType(), [i64])
    elif name == "astra_any_to_str":
        fnty = ir.FunctionType(i8p, [i64])
    elif name == "astra_any_to_ptr":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_any_is_none":
        fnty = ir.FunctionType(i1, [i64])
    elif name == "astra_len_any":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_len_str":
        fnty = ir.FunctionType(i64, [i8p])
    elif name == "astra_str_concat":
        fnty = ir.FunctionType(i8p, [i8p, i8p])
    elif name == "astra_read_file":
        fnty = ir.FunctionType(i8p, [i8p])
    elif name == "astra_write_file":
        fnty = ir.FunctionType(i64, [i8p, i8p])
    elif name == "astra_args":
        fnty = ir.FunctionType(i64, [])
    elif name == "astra_arg":
        fnty = ir.FunctionType(i8p, [i64])
    elif name == "astra_spawn_start":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_spawn_store":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_join":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_atomic_int_new":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_atomic_load":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_atomic_store":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_atomic_fetch_add":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_atomic_compare_exchange":
        fnty = ir.FunctionType(i1, [i64, i64, i64])
    elif name == "astra_mutex_new":
        fnty = ir.FunctionType(i64, [])
    elif name == "astra_mutex_lock":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_mutex_unlock":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_chan_new":
        fnty = ir.FunctionType(i64, [])
    elif name == "astra_chan_send":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_chan_recv_try":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_chan_recv_blocking":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_chan_close":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_list_new":
        fnty = ir.FunctionType(i64, [])
    elif name == "astra_list_push":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_list_get":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_list_set":
        fnty = ir.FunctionType(i64, [i64, i64, i64])
    elif name == "astra_list_len":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_map_new":
        fnty = ir.FunctionType(i64, [])
    elif name == "astra_map_has":
        fnty = ir.FunctionType(i1, [i64, i64])
    elif name == "astra_map_get":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_map_set":
        fnty = ir.FunctionType(i64, [i64, i64, i64])
    elif name == "astra_file_exists":
        fnty = ir.FunctionType(i1, [i8p])
    elif name == "astra_file_remove":
        fnty = ir.FunctionType(i64, [i8p])
    elif name == "astra_tcp_connect":
        fnty = ir.FunctionType(i64, [i8p])
    elif name == "astra_tcp_send":
        fnty = ir.FunctionType(i64, [i64, i8p])
    elif name == "astra_tcp_recv":
        fnty = ir.FunctionType(i8p, [i64, i64])
    elif name == "astra_tcp_close":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_to_json":
        fnty = ir.FunctionType(i8p, [i64])
    elif name == "astra_from_json":
        fnty = ir.FunctionType(i64, [i8p])
    elif name == "astra_sha256":
        fnty = ir.FunctionType(i8p, [i8p])
    elif name == "astra_hmac_sha256":
        fnty = ir.FunctionType(i8p, [i8p, i8p])
    elif name == "astra_rand_bytes":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_env_get":
        fnty = ir.FunctionType(i8p, [i8p])
    elif name == "astra_cwd":
        fnty = ir.FunctionType(i8p, [])
    elif name == "astra_proc_run":
        fnty = ir.FunctionType(i64, [i8p])
    elif name == "astra_now_unix":
        fnty = ir.FunctionType(i64, [])
    elif name == "astra_monotonic_ms":
        fnty = ir.FunctionType(i64, [])
    elif name == "astra_sleep_ms":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_alloc":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_free":
        fnty = ir.FunctionType(ir.VoidType(), [i64, i64, i64])
    elif name == "astra_panic":
        fnty = ir.FunctionType(ir.VoidType(), [i8p, i64])
    elif name == "astra_fmod":
        fnty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType(), ir.DoubleType()])
    elif name == "astra_print_int":
        fnty = ir.FunctionType(ir.VoidType(), [i64])
    elif name == "astra_print_bool":
        fnty = ir.FunctionType(ir.VoidType(), [i1])
    elif name == "astra_print_float":
        fnty = ir.FunctionType(ir.VoidType(), [ir.DoubleType()])
    elif name == "astra_int_to_str":
        fnty = ir.FunctionType(i8p, [i64])
    elif name == "astra_uint_to_str":
        fnty = ir.FunctionType(i8p, [i64])
    elif name == "astra_float_to_str":
        fnty = ir.FunctionType(i8p, [ir.DoubleType()])
    elif name == "astra_bool_to_str":
        fnty = ir.FunctionType(i8p, [i1])
    elif name == "astra_any_to_display":
        fnty = ir.FunctionType(i8p, [i64])
    elif name.startswith("astra_i128_"):
        fnty = ir.FunctionType(i128, [i128, i128])
    elif name.startswith("astra_u128_"):
        fnty = ir.FunctionType(i128, [i128, i128])
    else:
        raise CodegenError(f"internal: unknown runtime symbol {name}")
    fn = ir.Function(ctx.module, fnty, name=name)
    ctx.fn_map[name] = fn
    return fn


def _type_is_float_like(ty: str) -> bool:
    return _canonical_type(ty) in {"Float", "f16", "f32", "f64", "f80", "f128"}


def _value_to_string_ptr(ctx: _ModuleCtx, state: _FnState, value: _Value, node: Any) -> ir.Value:
    aty = _canonical_type(value.ty)
    b = state.builder
    if _is_option_type(aty):
        opt_val = _coerce_value(ctx, state, value.value, value.ty, aty, node)
        some_block = state.fn_ir.append_basic_block("fmt_opt_some")
        none_block = state.fn_ir.append_basic_block("fmt_opt_none")
        end_block = state.fn_ir.append_basic_block("fmt_opt_end")
        is_some = b.icmp_unsigned("!=", opt_val, ir.Constant(opt_val.type, None))
        b.cbranch(is_some, some_block, none_block)

        b.position_at_end(some_block)
        inner_ty = _option_inner_type(aty)
        inner_ptr = b.bitcast(opt_val, _llvm_type(ctx, inner_ty).as_pointer())
        inner_raw = b.load(inner_ptr)
        inner_text = _value_to_string_ptr(ctx, state, _Value(inner_raw, inner_ty), node)
        b.branch(end_block)
        some_block = b.block

        b.position_at_end(none_block)
        none_str = _get_string_global(ctx, "none")
        none_text = b.gep(none_str, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
        b.branch(end_block)
        none_block = b.block

        b.position_at_end(end_block)
        out = b.phi(ir.IntType(8).as_pointer())
        out.add_incoming(inner_text, some_block)
        out.add_incoming(none_text, none_block)
        return out
    if aty in {"String", "str"}:
        return _coerce_value(ctx, state, value.value, value.ty, "String", node)
    if aty == "Any":
        any_val = _coerce_value(ctx, state, value.value, value.ty, "Any", node)
        to_display_fn = _declare_runtime(ctx, "astra_any_to_display")
        return b.call(to_display_fn, [any_val])
    if aty == "Bool":
        to_str_fn = _declare_runtime(ctx, "astra_bool_to_str")
        as_bool = _coerce_value(ctx, state, value.value, value.ty, "Bool", node)
        return b.call(to_str_fn, [as_bool])
    int_info = parse_int_type_name(aty)
    if int_info is not None and int_info[0] <= 64:
        if int_info[1]:
            to_str_fn = _declare_runtime(ctx, "astra_int_to_str")
            as_int = _coerce_value(ctx, state, value.value, value.ty, "Int", node)
            return b.call(to_str_fn, [as_int])
        to_str_fn = _declare_runtime(ctx, "astra_uint_to_str")
        as_uint = _coerce_value(ctx, state, value.value, value.ty, "usize", node)
        return b.call(to_str_fn, [as_uint])
    if aty == "Char":
        to_str_fn = _declare_runtime(ctx, "astra_int_to_str")
        as_int = _coerce_value(ctx, state, value.value, value.ty, "Int", node)
        return b.call(to_str_fn, [as_int])
    if _type_is_float_like(aty):
        to_str_fn = _declare_runtime(ctx, "astra_float_to_str")
        as_float = _coerce_value(ctx, state, value.value, value.ty, "Float", node)
        return b.call(to_str_fn, [as_float])
    boxed_arg = _coerce_value(ctx, state, value.value, value.ty, "Any", node)
    to_display_fn = _declare_runtime(ctx, "astra_any_to_display")
    return b.call(to_display_fn, [boxed_arg])


def _concat_string_ptrs(ctx: _ModuleCtx, state: _FnState, parts: list[ir.Value]) -> ir.Value:
    b = state.builder
    if not parts:
        empty = _get_string_global(ctx, "")
        return b.gep(empty, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
    out = parts[0]
    for part in parts[1:]:
        concat_fn = _declare_runtime(ctx, "astra_str_concat")
        out = b.call(concat_fn, [out, part])
    return out


def _compile_string_interpolation(ctx: _ModuleCtx, state: _FnState, interp: StringInterpolation) -> _Value:
    """Compile string interpolation to a string value."""
    b = state.builder
    parts: list[ir.Value] = []
    for i, chunk in enumerate(interp.parts):
        if chunk:
            g = _get_string_global(ctx, chunk)
            chunk_ptr = b.gep(g, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
            parts.append(chunk_ptr)
        if i < len(interp.exprs):
            expr = interp.exprs[i]
            arg = _compile_expr(ctx, state, expr)
            parts.append(_value_to_string_ptr(ctx, state, arg, expr))
    return _Value(_concat_string_ptrs(ctx, state, parts), "String")


def _declare_intrinsic(ctx: _ModuleCtx, base: str, bits: int) -> ir.Function:
    name = f"llvm.{base}.i{bits}"
    fn = ctx.fn_map.get(name)
    if isinstance(fn, ir.Function):
        return fn
    it = ir.IntType(bits)
    if base in {"ctlz", "cttz"}:
        fnty = ir.FunctionType(it, [it, ir.IntType(1)])
    else:
        fnty = ir.FunctionType(it, [it])
    fn = ir.Function(ctx.module, fnty, name=name)
    ctx.fn_map[name] = fn
    return fn


def _declare_fptoi_sat_intrinsic(ctx: _ModuleCtx, bits: int, signed: bool, from_ty: ir.Type) -> ir.Function:
    if isinstance(from_ty, ir.FloatType):
        src = "f32"
    elif isinstance(from_ty, ir.DoubleType):
        src = "f64"
    else:
        raise CodegenError(f"internal: unsupported float source type for saturating cast: {from_ty}")
    op = "fptosi" if signed else "fptoui"
    name = f"llvm.{op}.sat.i{bits}.{src}"
    fn = ctx.fn_map.get(name)
    if isinstance(fn, ir.Function):
        return fn
    fnty = ir.FunctionType(ir.IntType(bits), [from_ty])
    fn = ir.Function(ctx.module, fnty, name=name)
    ctx.fn_map[name] = fn
    return fn


def _declare_trap(ctx: _ModuleCtx) -> ir.Function:
    name = "llvm.trap"
    fn = ctx.fn_map.get(name)
    if isinstance(fn, ir.Function):
        return fn
    fn = ir.Function(ctx.module, ir.FunctionType(ir.VoidType(), []), name=name)
    ctx.fn_map[name] = fn
    return fn


def _declare_memcpy(ctx: _ModuleCtx) -> ir.Function:
    name = "llvm.memcpy.p0.p0.i64"
    fn = ctx.fn_map.get(name)
    if isinstance(fn, ir.Function):
        return fn
    i8p = ir.IntType(8).as_pointer()
    i64 = ir.IntType(64)
    i1 = ir.IntType(1)
    fn = ir.Function(ctx.module, ir.FunctionType(ir.VoidType(), [i8p, i8p, i64, i1]), name=name)
    ctx.fn_map[name] = fn
    return fn


def _ensure_freestanding_heap(ctx: _ModuleCtx) -> tuple[ir.GlobalVariable, ir.GlobalVariable]:
    heap_name = "__astra_fs_heap"
    off_name = "__astra_fs_heap_off"
    try:
        heap = ctx.module.get_global(heap_name)
    except KeyError:
        heap_ty = ir.ArrayType(ir.IntType(8), _FREESTANDING_HEAP_BYTES)
        heap = ir.GlobalVariable(ctx.module, heap_ty, name=heap_name)
        heap.linkage = "internal"
        heap.initializer = ir.Constant(heap_ty, None)
    try:
        off = ctx.module.get_global(off_name)
    except KeyError:
        off_ty = ir.IntType(64)
        off = ir.GlobalVariable(ctx.module, off_ty, name=off_name)
        off.linkage = "internal"
        off.initializer = ir.Constant(off_ty, 0)
    return heap, off


def _alloc_bytes(
    ctx: _ModuleCtx,
    state: _FnState,
    size_i64: ir.Value,
    align_i64: ir.Value,
    node: Any,
    *,
    stack_ok: bool = False,
) -> ir.Value:
    b = state.builder
    i64 = ir.IntType(64)
    i8p = ir.IntType(8).as_pointer()
    if stack_ok and state.stack_alloc_depth > 0 and not state.loop_stack and not ctx.freestanding:
        size_v = size_i64
        if not isinstance(size_v.type, ir.IntType):
            raise CodegenError(_diag(node, f"internal: allocator size must be integer, got {size_v.type}"))
        if isinstance(size_v, ir.Constant):
            size_const = int(size_v.constant)
            if size_const <= 0:
                size_v = ir.Constant(size_v.type, 1)
        else:
            zero_sz = ir.Constant(size_v.type, 0)
            one_sz = ir.Constant(size_v.type, 1)
            is_zero = b.icmp_unsigned("==", size_v, zero_sz)
            size_v = b.select(is_zero, one_sz, size_v)
        stack_mem = b.alloca(ir.IntType(8), size=size_v, name="stack_mem")
        if isinstance(align_i64, ir.Constant):
            align_const = int(align_i64.constant)
            if align_const > 0:
                stack_mem.align = align_const
        if stack_mem.type != i8p:
            return b.bitcast(stack_mem, i8p)
        return stack_mem

    if not ctx.freestanding:
        alloc_fn = _declare_runtime(ctx, "astra_alloc")
        raw = b.call(alloc_fn, [size_i64, align_i64])
        return b.inttoptr(raw, i8p)

    heap, off = _ensure_freestanding_heap(ctx)
    zero = ir.Constant(i64, 0)
    one = ir.Constant(i64, 1)
    old_off = b.load(off)
    align_nz = b.select(b.icmp_unsigned("==", align_i64, zero), one, align_i64)
    mask = b.sub(align_nz, one)
    plus = b.add(old_off, mask)
    inv_mask = b.xor(mask, ir.Constant(i64, -1))
    aligned_off = b.and_(plus, inv_mask)
    new_off = b.add(aligned_off, size_i64)
    ok = b.icmp_unsigned("<=", new_off, ir.Constant(i64, _FREESTANDING_HEAP_BYTES))

    fn = state.fn_ir
    ok_block = fn.append_basic_block("fs_alloc_ok")
    oom_block = fn.append_basic_block("fs_alloc_oom")
    b.cbranch(ok, ok_block, oom_block)

    b.position_at_end(oom_block)
    trap = _declare_trap(ctx)
    b.call(trap, [])
    b.unreachable()

    b.position_at_end(ok_block)
    b.store(new_off, off)
    ptr = b.gep(heap, [zero, aligned_off])
    if ptr.type != i8p:
        ptr = b.bitcast(ptr, i8p)
    return ptr


def _as_i8_ptr(state: _FnState, v: ir.Value, node: Any) -> ir.Value:
    i8p = ir.IntType(8).as_pointer()
    if isinstance(v.type, ir.PointerType):
        if v.type == i8p:
            return v
        return state.builder.bitcast(v, i8p)
    if isinstance(v.type, ir.IntType):
        return state.builder.inttoptr(v, i8p)
    raise CodegenError(_diag(node, f"expected pointer-like value, got {v.type}"))


def _sequence_parts(ctx: _ModuleCtx, state: _FnState, obj_expr: Any, overflow_mode: str, node: Any) -> tuple[str, ir.Value, ir.Value]:
    obj_ty = _expr_type(state, obj_expr)
    base_ty = _strip_ref_type(obj_ty)
    if _is_vec_type(base_ty):
        elem_ty = _vec_inner_type(base_ty)
    elif _is_slice_type(base_ty):
        elem_ty = _slice_inner_type(base_ty)
    else:
        raise CodegenError(_diag(node, f"index/get expects Vec<T> or [T], got {obj_ty}"))

    # Lightweight escape-aware optimization: sequence literals used directly in
    # indexing/get/len contexts do not escape, so keep them on the stack.
    if isinstance(obj_expr, ArrayLit):
        b = state.builder
        elem_ll = _llvm_type(ctx, elem_ty)
        vals: list[ir.Value] = []
        for el in obj_expr.elements:
            v = _compile_expr(ctx, state, el, overflow_mode=overflow_mode)
            vals.append(_coerce_value(ctx, state, v.value, v.ty, elem_ty, el))
        ln = ir.Constant(ir.IntType(64), len(vals))
        if vals:
            arr_ty = ir.ArrayType(elem_ll, len(vals))
            arr_ptr = b.alloca(arr_ty)
            for i, vv in enumerate(vals):
                ep = b.gep(arr_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
                b.store(vv, ep)
            data = b.bitcast(arr_ptr, ir.IntType(8).as_pointer())
        else:
            data = ir.Constant(ir.IntType(8).as_pointer(), None)
        return elem_ty, ln, data

    obj = _compile_expr(ctx, state, obj_expr, overflow_mode=overflow_mode)
    handle = obj.value
    if _canonical_type(obj_ty).startswith("&"):
        if not isinstance(handle.type, ir.PointerType):
            raise CodegenError(_diag(node, f"cannot index through non-pointer reference type {obj_ty}"))
        handle = state.builder.load(handle)
    handle_i8 = _as_i8_ptr(state, handle, node)
    hdr_ptr = state.builder.bitcast(handle_i8, ctx.slice_header_ty.as_pointer())
    len_ptr = state.builder.gep(hdr_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
    data_ptr = state.builder.gep(hdr_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
    ln = state.builder.load(len_ptr)
    data = state.builder.load(data_ptr)
    return elem_ty, ln, data


def _sequence_parts_from_value(
    ctx: _ModuleCtx,
    state: _FnState,
    seq: _Value,
    node: Any,
) -> tuple[str, ir.Value, ir.Value] | None:
    seq_ty = _canonical_type(seq.ty)
    base_ty = _strip_ref_type(seq_ty)
    if _is_vec_type(base_ty):
        elem_ty = _vec_inner_type(base_ty)
    elif _is_slice_type(base_ty):
        elem_ty = _slice_inner_type(base_ty)
    else:
        return None

    handle = seq.value
    if seq_ty.startswith("&"):
        if not isinstance(handle.type, ir.PointerType):
            return None
        handle = state.builder.load(handle)
    handle_i8 = _as_i8_ptr(state, handle, node)
    hdr_ptr = state.builder.bitcast(handle_i8, ctx.slice_header_ty.as_pointer())
    len_ptr = state.builder.gep(hdr_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
    data_ptr = state.builder.gep(hdr_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
    ln = state.builder.load(len_ptr)
    data = state.builder.load(data_ptr)
    return elem_ty, ln, data


def _compile_index_base(
    ctx: _ModuleCtx,
    state: _FnState,
    obj_expr: Any,
    idx_expr: Any,
    overflow_mode: str,
    node: Any,
) -> tuple[str, ir.Type, ir.Value, ir.Value, ir.Value]:
    elem_ty, ln, data_i8 = _sequence_parts(ctx, state, obj_expr, overflow_mode, node)
    idx = _compile_expr(ctx, state, idx_expr, overflow_mode=overflow_mode)
    idx64 = _coerce_value(ctx, state, idx.value, idx.ty, "Int", idx_expr)
    elem_ll = _llvm_type(ctx, elem_ty)
    data_ptr = state.builder.bitcast(data_i8, elem_ll.as_pointer())
    return elem_ty, elem_ll, idx64, ln, data_ptr


def _emit_oob_trap(ctx: _ModuleCtx, state: _FnState, idx64: ir.Value, ln: ir.Value) -> None:
    b = state.builder
    fn = state.fn_ir
    zero = ir.Constant(ir.IntType(64), 0)
    nonneg = b.icmp_signed(">=", idx64, zero)
    lt = b.icmp_signed("<", idx64, ln)
    ok = b.and_(nonneg, lt)
    in_bounds = fn.append_basic_block("idx_in_bounds")
    oob = fn.append_basic_block("idx_oob")
    b.cbranch(ok, in_bounds, oob)

    b.position_at_end(oob)
    trap = _declare_trap(ctx)
    b.call(trap, [])
    b.unreachable()

    b.position_at_end(in_bounds)


def _emit_shift_trap_guard(ctx: _ModuleCtx, state: _FnState, rv: ir.Value, signed: bool, bits: int) -> None:
    if not isinstance(rv.type, ir.IntType):
        raise CodegenError("internal: shift rhs must be integer")
    b = state.builder
    fn = state.fn_ir
    max_shift = ir.Constant(rv.type, bits)
    
    if signed:
        # For signed: need 0 <= shift < bits
        nonneg = b.icmp_signed(">=", rv, ir.Constant(rv.type, 0))
        lt_bits = b.icmp_signed("<", rv, max_shift)
        ok = b.and_(nonneg, lt_bits)
    else:
        # For unsigned: only need shift < bits (shift is always >= 0)
        ok = b.icmp_unsigned("<", rv, max_shift)
    
    in_range = fn.append_basic_block("shift_in_range")
    bad = fn.append_basic_block("shift_oob")
    b.cbranch(ok, in_range, bad)

    b.position_at_end(bad)
    trap = _declare_trap(ctx)
    b.call(trap, [])
    b.unreachable()

    b.position_at_end(in_range)


def _emit_divrem_trap_guard(ctx: _ModuleCtx, state: _FnState, lv: ir.Value, rv: ir.Value, signed: bool) -> None:
    if not isinstance(lv.type, ir.IntType) or not isinstance(rv.type, ir.IntType):
        raise CodegenError("internal: checked div/rem requires integer operands")
    if lv.type.width != rv.type.width:
        raise CodegenError("internal: checked div/rem requires matching integer widths")

    b = state.builder
    fn = state.fn_ir
    zero = ir.Constant(rv.type, 0)
    bad = b.icmp_unsigned("==", rv, zero)
    if signed:
        min_v = ir.Constant(lv.type, 1 << (lv.type.width - 1))
        neg_one = ir.Constant(rv.type, -1)
        min_div_neg_one = b.and_(
            b.icmp_signed("==", lv, min_v),
            b.icmp_signed("==", rv, neg_one),
        )
        bad = b.or_(bad, min_div_neg_one)

    ok_block = fn.append_basic_block("divrem_ok")
    bad_block = fn.append_basic_block("divrem_bad")
    b.cbranch(bad, bad_block, ok_block)

    b.position_at_end(bad_block)
    trap = _declare_trap(ctx)
    b.call(trap, [])
    b.unreachable()

    b.position_at_end(ok_block)


def _lower_checked_divrem(
    ctx: _ModuleCtx,
    state: _FnState,
    lv: ir.Value,
    rv: ir.Value,
    signed: bool,
    is_div: bool,
) -> ir.Value:
    _emit_divrem_trap_guard(ctx, state, lv, rv, signed=signed)
    b = state.builder
    if is_div:
        return b.sdiv(lv, rv) if signed else b.udiv(lv, rv)
    return b.srem(lv, rv) if signed else b.urem(lv, rv)


def _lower_checked_shift(
    ctx: _ModuleCtx,
    state: _FnState,
    lv: ir.Value,
    rv: ir.Value,
    signed: bool,
    left_shift: bool,
) -> ir.Value:
    if not isinstance(lv.type, ir.IntType) or not isinstance(rv.type, ir.IntType):
        raise CodegenError("internal: checked shift requires integer operands")
    _emit_shift_trap_guard(ctx, state, rv, signed=signed, bits=lv.type.width)
    b = state.builder
    if left_shift:
        return b.shl(lv, rv)
    return b.ashr(lv, rv) if signed else b.lshr(lv, rv)


def _lower_count_like(ctx: _ModuleCtx, state: _FnState, call: Call, op: str) -> _Value:
    if len(call.args) != 1:
        raise CodegenError(_diag(call, f"{op} expects 1 argument"))
    arg = _compile_expr(ctx, state, call.args[0])
    info = _int_info(arg.ty)
    if info is None:
        raise CodegenError(_diag(call, f"{op} expects integer argument"))
    bits, _ = info
    v = _coerce_value(ctx, state, arg.value, arg.ty, arg.ty, call)
    if op == "countOnes":
        intr = _declare_intrinsic(ctx, "ctpop", bits)
        out = state.builder.call(intr, [v])
    elif op == "leadingZeros":
        intr = _declare_intrinsic(ctx, "ctlz", bits)
        out = state.builder.call(intr, [v, ir.Constant(ir.IntType(1), 0)])
    else:
        intr = _declare_intrinsic(ctx, "cttz", bits)
        out = state.builder.call(intr, [v, ir.Constant(ir.IntType(1), 0)])
    out64 = out if bits == 64 else state.builder.zext(out, ir.IntType(64))
    if bits > 64:
        out64 = state.builder.trunc(out64, ir.IntType(64))
    return _Value(out64, "Int")


def _lower_rotate(ctx: _ModuleCtx, state: _FnState, call: Call, left: bool, overflow_mode: str) -> _Value:
    if len(call.args) != 2:
        name = "rotl" if left else "rotr"
        raise CodegenError(_diag(call, f"{name} expects 2 arguments"))
    x = _compile_expr(ctx, state, call.args[0], overflow_mode=overflow_mode)
    info = _int_info(x.ty)
    if info is None:
        name = "rotl" if left else "rotr"
        raise CodegenError(_diag(call, f"{name} expects integer arg 0"))
    bits, _ = info
    rhs = _compile_expr(ctx, state, call.args[1], overflow_mode=overflow_mode)
    rhs64 = _coerce_value(ctx, state, rhs.value, rhs.ty, "Int", call.args[1])
    xt = _coerce_value(ctx, state, x.value, x.ty, x.ty, call.args[0])
    b = state.builder
    n64 = b.urem(rhs64, ir.Constant(ir.IntType(64), bits))
    if xt.type.width == 64:
        n = n64
    elif xt.type.width < 64:
        n = b.trunc(n64, xt.type)
    else:
        n = b.zext(n64, xt.type)
    bits_v = ir.Constant(xt.type, bits)
    inv = b.urem(b.sub(bits_v, n), bits_v)
    if left:
        a = b.shl(xt, n)
        c = b.lshr(xt, inv)
    else:
        a = b.lshr(xt, n)
        c = b.shl(xt, inv)
    return _Value(b.or_(a, c), x.ty)


def _i128_helper_symbol(op: str, signed: bool, overflow_mode: str) -> str:
    mode = "trap" if overflow_mode == "trap" else "wrap"
    prefix = "i128" if signed else "u128"
    return f"astra_{prefix}_{op}_{mode}"


def _compile_builtin_call(ctx: _ModuleCtx, state: _FnState, call: Call, name: str, overflow_mode: str) -> _Value:
    base = name[2:] if name.startswith("__") else name
    b = state.builder
    i64 = ir.IntType(64)
    i8p = ir.IntType(8).as_pointer()

    def _as_string_ptr(v: _Value, node: Any) -> ir.Value:
        return _coerce_value(ctx, state, v.value, v.ty, "String", node)

    def _as_i64(v: _Value, node: Any) -> ir.Value:
        return _coerce_value(ctx, state, v.value, v.ty, "Int", node)

    def _as_any_i64(v: _Value, node: Any) -> ir.Value:
        return _coerce_value(ctx, state, v.value, v.ty, "Any", node)

    def _spawn_entry_wrapper(arity: int) -> ir.Function:
        key = f"__astra_spawn_entry_i64_{arity}"
        existing = ctx.fn_map.get(key)
        if isinstance(existing, ir.Function):
            return existing
        payload_i64p = i64.as_pointer()
        wrapper = ir.Function(ctx.module, ir.FunctionType(i64, [i64]), name=key)
        ctx.fn_map[key] = wrapper
        wb = ir.IRBuilder(wrapper.append_basic_block("entry"))
        payload_ptr = wb.inttoptr(wrapper.args[0], payload_i64p)
        fn_bits_ptr = wb.gep(payload_ptr, [ir.Constant(i64, 0)])
        fn_bits = wb.load(fn_bits_ptr)
        worker_ty = ir.FunctionType(i64, [i64 for _ in range(arity)])
        worker_ptr = wb.inttoptr(fn_bits, worker_ty.as_pointer())
        args: list[ir.Value] = []
        for idx in range(arity):
            arg_ptr = wb.gep(payload_ptr, [ir.Constant(i64, idx + 1)])
            args.append(wb.load(arg_ptr))
        free_fn = _declare_runtime(ctx, "astra_free")
        payload_size = ir.Constant(i64, (arity + 1) * 8)
        wb.call(free_fn, [wrapper.args[0], payload_size, ir.Constant(i64, 8)])
        out = wb.call(worker_ptr, args)
        wb.ret(out)
        return wrapper

    if base == "vec_new":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "vec_new expects 0 arguments"))
        header_i8 = _alloc_bytes(ctx, state, ir.Constant(i64, 16), ir.Constant(i64, 8), call, stack_ok=True)
        header_ptr = b.bitcast(header_i8, ctx.slice_header_ty.as_pointer())
        len_ptr = b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
        data_ptr = b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
        b.store(ir.Constant(i64, 0), len_ptr)
        b.store(ir.Constant(i8p, None), data_ptr)
        out_ty = _expr_type(state, call)
        if _is_vec_type(out_ty):
            return _Value(header_i8, out_ty)
        boxed = _coerce_value(ctx, state, header_i8, "&u8", "Any", call)
        return _Value(boxed, "Any")

    if base == "vec_from":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "vec_from expects 1 argument"))
        src = _compile_expr(ctx, state, call.args[0], overflow_mode=overflow_mode)
        src_ty = _canonical_type(src.ty)
        if _is_vec_type(src_ty):
            return _Value(_as_i8_ptr(state, src.value, call), src_ty)
        if _is_slice_type(src_ty):
            return _Value(_as_i8_ptr(state, src.value, call), f"Vec<{_slice_inner_type(src_ty)}>")
        raise CodegenError(_diag(call, f"vec_from expects [T] or Vec<T>, got {src.ty}"))

    if base in {"vec_len", "vec_get", "vec_set", "vec_push"}:
        if len(call.args) < 1:
            raise CodegenError(_diag(call, f"{base} expects at least 1 argument"))
        vec = _compile_expr(ctx, state, call.args[0], overflow_mode=overflow_mode)
        vec_ty = _canonical_type(vec.ty)
        if not _is_vec_type(vec_ty):
            raise CodegenError(_diag(call, f"{base} expects Vec<T>, got {vec.ty}"))
        elem_ty = _vec_inner_type(vec_ty)
        vec_i8 = _as_i8_ptr(state, vec.value, call.args[0])
        hdr_ptr = b.bitcast(vec_i8, ctx.slice_header_ty.as_pointer())
        len_ptr = b.gep(hdr_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
        data_ptr = b.gep(hdr_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
        ln = b.load(len_ptr)

        if base == "vec_len":
            if len(call.args) != 1:
                raise CodegenError(_diag(call, "vec_len expects 1 argument"))
            return _Value(ln, "Int")

        idx = _compile_expr(ctx, state, call.args[1], overflow_mode=overflow_mode)
        idx64 = _coerce_value(ctx, state, idx.value, idx.ty, "Int", call.args[1])
        elem_ll = _llvm_type(ctx, elem_ty)
        data_i8 = b.load(data_ptr)
        typed_data = b.bitcast(data_i8, elem_ll.as_pointer())

        if base == "vec_get":
            if len(call.args) != 2:
                raise CodegenError(_diag(call, "vec_get expects 2 arguments"))
            zero = ir.Constant(ir.IntType(64), 0)
            nonneg = b.icmp_signed(">=", idx64, zero)
            lt = b.icmp_signed("<", idx64, ln)
            in_bounds = b.and_(nonneg, lt)
            some_block = state.fn_ir.append_basic_block("vec_get_some")
            none_block = state.fn_ir.append_basic_block("vec_get_none")
            end_block = state.fn_ir.append_basic_block("vec_get_end")
            b.cbranch(in_bounds, some_block, none_block)

            b.position_at_end(some_block)
            elem_ptr = b.gep(typed_data, [idx64])
            some_val = _as_i8_ptr(state, elem_ptr, call)
            b.branch(end_block)
            some_block = b.block

            b.position_at_end(none_block)
            b.branch(end_block)
            none_block = b.block

            b.position_at_end(end_block)
            out = b.phi(ir.IntType(8).as_pointer())
            out.add_incoming(some_val, some_block)
            out.add_incoming(ir.Constant(ir.IntType(8).as_pointer(), None), none_block)
            return _Value(out, f"Option<{elem_ty}>")

        if base == "vec_set":
            if len(call.args) != 3:
                raise CodegenError(_diag(call, "vec_set expects 3 arguments"))
            _emit_oob_trap(ctx, state, idx64, ln)
            elem_ptr = b.gep(typed_data, [idx64])
            val = _compile_expr(ctx, state, call.args[2], overflow_mode=overflow_mode)
            vv = _coerce_value(ctx, state, val.value, val.ty, elem_ty, call.args[2])
            b.store(vv, elem_ptr)
            return _Value(ir.Constant(i64, 0), "Int")

        if base == "vec_push":
            if len(call.args) != 2:
                raise CodegenError(_diag(call, "vec_push expects 2 arguments"))
            elem_sz, elem_align = _storage_size_align(ctx, elem_ty, call)
            new_ln = b.add(ln, ir.Constant(i64, 1))
            new_bytes = b.mul(new_ln, ir.Constant(i64, elem_sz))
            new_data_i8 = _alloc_bytes(ctx, state, new_bytes, ir.Constant(i64, elem_align), call)

            zero = ir.Constant(i64, 0)
            has_old = b.icmp_unsigned(">", ln, zero)
            copy_block = state.fn_ir.append_basic_block("vec_push_copy")
            nocopy_block = state.fn_ir.append_basic_block("vec_push_nocopy")
            cont_block = state.fn_ir.append_basic_block("vec_push_cont")
            b.cbranch(has_old, copy_block, nocopy_block)

            b.position_at_end(copy_block)
            old_bytes = b.mul(ln, ir.Constant(i64, elem_sz))
            memcpy = _declare_memcpy(ctx)
            b.call(memcpy, [new_data_i8, data_i8, old_bytes, ir.Constant(ir.IntType(1), 0)])
            b.branch(cont_block)

            b.position_at_end(nocopy_block)
            b.branch(cont_block)

            b.position_at_end(cont_block)
            new_typed = b.bitcast(new_data_i8, elem_ll.as_pointer())
            tail_ptr = b.gep(new_typed, [ln])
            val = _compile_expr(ctx, state, call.args[1], overflow_mode=overflow_mode)
            vv = _coerce_value(ctx, state, val.value, val.ty, elem_ty, call.args[1])
            b.store(vv, tail_ptr)
            b.store(new_ln, len_ptr)
            b.store(new_data_i8, data_ptr)
            return _Value(ir.Constant(i64, 0), "Int")

    if base == "print":
        parts = []
        for i, arg_node in enumerate(call.args):
            if isinstance(arg_node, StringInterpolation):
                compiled_str = _compile_string_interpolation(ctx, state, arg_node)
                parts.append(compiled_str.value)
            elif isinstance(arg_node, Literal) and isinstance(arg_node.value, str):
                g = _get_string_global(ctx, arg_node.value)
                ptr = b.gep(g, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
                parts.append(ptr)
            else:
                arg = _compile_expr(ctx, state, arg_node)
                parts.append(_value_to_string_ptr(ctx, state, arg, arg_node))
            
            # Add space between arguments (except last)
            if i < len(call.args) - 1:
                space_str = _get_string_global(ctx, " ")
                space_ptr = b.gep(space_str, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
                parts.append(space_ptr)

        final_ptr = _concat_string_ptrs(ctx, state, parts)
        len_fn = _declare_runtime(ctx, "astra_len_str")
        final_len = b.call(len_fn, [final_ptr])
        fn = _declare_runtime(ctx, "astra_print_str")
        b.call(fn, [final_ptr, final_len])
        return _Value(ir.Constant(i64, 0), "Int")

    if base == "format":
        # Format function returns a string instead of printing
        if len(call.args) == 1 and isinstance(call.args[0], StringInterpolation):
            # Single string interpolation argument
            return _compile_string_interpolation(ctx, state, call.args[0])
        elif len(call.args) == 1:
            # Single argument - convert to string if needed
            arg_node = call.args[0]
            arg = _compile_expr(ctx, state, arg_node)
            str_val = _value_to_string_ptr(ctx, state, arg, arg_node)
            return _Value(str_val, "String")
        else:
            parts = []
            for i, arg_node in enumerate(call.args):
                if isinstance(arg_node, StringInterpolation):
                    compiled_str = _compile_string_interpolation(ctx, state, arg_node)
                    parts.append(compiled_str.value)
                else:
                    arg = _compile_expr(ctx, state, arg_node)
                    parts.append(_value_to_string_ptr(ctx, state, arg, arg_node))
                
                # Add space between arguments (except last)
                if i < len(call.args) - 1:
                    space_str = _get_string_global(ctx, " ")
                    space_ptr = b.gep(space_str, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
                    parts.append(space_ptr)

            return _Value(_concat_string_ptrs(ctx, state, parts), "String")

    if base == "len":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "len expects 1 argument"))
        a = _compile_expr(ctx, state, call.args[0])
        aty = _canonical_type(a.ty)
        if aty in {"String", "str"}:
            fn = _declare_runtime(ctx, "astra_len_str")
            sp = _as_string_ptr(a, call.args[0])
            return _Value(b.call(fn, [sp]), "Int")
        if _is_vec_type(_strip_ref_type(aty)) or _is_slice_type(_strip_ref_type(aty)):
            _, ln, _ = _sequence_parts(ctx, state, call.args[0], overflow_mode, call)
            return _Value(ln, "Int")
        fn = _declare_runtime(ctx, "astra_len_any")
        av = _as_any_i64(a, call.args[0])
        return _Value(b.call(fn, [av]), "Int")

    if base == "read_file":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "read_file expects 1 argument"))
        p = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_read_file")
        out = b.call(fn, [_as_string_ptr(p, call.args[0])])
        return _Value(out, "String")

    if base == "write_file":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "write_file expects 2 arguments"))
        p = _compile_expr(ctx, state, call.args[0])
        d = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_write_file")
        out = b.call(fn, [_as_string_ptr(p, call.args[0]), _as_string_ptr(d, call.args[1])])
        return _Value(out, "Int")

    if base == "args":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "args expects 0 arguments"))
        fn = _declare_runtime(ctx, "astra_args")
        return _Value(b.call(fn, []), "Any")

    if base == "arg":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "arg expects 1 argument"))
        idx = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_arg")
        out = b.call(fn, [_as_i64(idx, call.args[0])])
        return _Value(out, "String")

    if base == "spawn":
        if len(call.args) < 1:
            raise CodegenError(_diag(call, "spawn expects at least a function argument"))
        _declare_runtime(ctx, "astra_spawn_store")
        worker = _compile_expr(ctx, state, call.args[0], overflow_mode=overflow_mode)
        parsed = _parse_fn_type(worker.ty)
        if parsed is None:
            if worker.ty == "Any":
                # Handle case where worker function is typed as Any
                # Infer parameter types from actual arguments
                worker_param_tys = []
                for arg in call.args[1:]:
                    arg_val = _compile_expr(ctx, state, arg, overflow_mode=overflow_mode)
                    worker_param_tys.append(arg_val.ty)
                worker_ret_ty = "Int"
                worker_unsafe = False
            else:
                raise CodegenError(_diag(call, f"spawn expects function reference, got {worker.ty}"))
        else:
            worker_param_tys, worker_ret_ty, worker_unsafe = parsed
        if len(worker_param_tys) != len(call.args) - 1:
            raise CodegenError(
                _diag(call, f"spawn worker expects {len(worker_param_tys)} args, got {len(call.args) - 1}")
            )
        if _canonical_type(worker_ret_ty) != "Int":
            raise CodegenError(_diag(call, "spawn currently requires worker return type Int"))
        for idx, pty in enumerate(worker_param_tys):
            if _canonical_type(pty) != "Int":
                raise CodegenError(_diag(call.args[idx + 1], "spawn currently supports only Int worker parameters"))
        arity = len(worker_param_tys)
        payload_ptr_i8 = _alloc_bytes(ctx, state, ir.Constant(i64, (arity + 1) * 8), ir.Constant(i64, 8), call)
        payload_ptr = b.bitcast(payload_ptr_i8, i64.as_pointer())
        if _canonical_type(worker.ty) == "Any":
            any_v = worker.value
            if not (isinstance(any_v.type, ir.IntType) and any_v.type.width == 64):
                any_v = b.bitcast(any_v, i64)
            to_i64 = _declare_runtime(ctx, "astra_any_to_i64")
            worker_bits = b.call(to_i64, [any_v])
        else:
            worker_ptr_i8 = _as_i8_ptr(state, worker.value, call.args[0])
            worker_bits = b.ptrtoint(worker_ptr_i8, i64)
        b.store(worker_bits, b.gep(payload_ptr, [ir.Constant(i64, 0)]))
        for idx, arg_node in enumerate(call.args[1:]):
            av = _compile_expr(ctx, state, arg_node, overflow_mode=overflow_mode)
            ai64 = _as_i64(av, arg_node)
            b.store(ai64, b.gep(payload_ptr, [ir.Constant(i64, idx + 1)]))
        wrapper = _spawn_entry_wrapper(arity)
        wrapper_bits = b.ptrtoint(wrapper, i64)
        fn = _declare_runtime(ctx, "astra_spawn_start")
        tid = b.call(fn, [wrapper_bits, b.ptrtoint(payload_ptr_i8, i64)])
        return _Value(tid, "Int")

    if base == "join":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "join expects 1 argument"))
        t = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_join")
        out = b.call(fn, [_as_i64(t, call.args[0])])
        return _Value(out, "Any")

    if base == "atomic_int_new":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "atomic_int_new expects 1 argument"))
        v = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_atomic_int_new")
        out = b.call(fn, [_as_i64(v, call.args[0])])
        return _Value(out, "Int")

    if base == "atomic_load":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "atomic_load expects 1 argument"))
        h = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_atomic_load")
        out = b.call(fn, [_as_i64(h, call.args[0])])
        return _Value(out, "Int")

    if base == "atomic_store":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "atomic_store expects 2 arguments"))
        h = _compile_expr(ctx, state, call.args[0])
        v = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_atomic_store")
        out = b.call(fn, [_as_i64(h, call.args[0]), _as_i64(v, call.args[1])])
        return _Value(out, "Int")

    if base == "atomic_fetch_add":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "atomic_fetch_add expects 2 arguments"))
        h = _compile_expr(ctx, state, call.args[0])
        d = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_atomic_fetch_add")
        out = b.call(fn, [_as_i64(h, call.args[0]), _as_i64(d, call.args[1])])
        return _Value(out, "Int")

    if base == "atomic_compare_exchange":
        if len(call.args) != 3:
            raise CodegenError(_diag(call, "atomic_compare_exchange expects 3 arguments"))
        h = _compile_expr(ctx, state, call.args[0])
        expected = _compile_expr(ctx, state, call.args[1])
        desired = _compile_expr(ctx, state, call.args[2])
        fn = _declare_runtime(ctx, "astra_atomic_compare_exchange")
        out = b.call(
            fn,
            [_as_i64(h, call.args[0]), _as_i64(expected, call.args[1]), _as_i64(desired, call.args[2])],
        )
        return _Value(out, "Bool")

    if base == "list_new":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "list_new expects 0 arguments"))
        fn = _declare_runtime(ctx, "astra_list_new")
        return _Value(b.call(fn, []), "Any")

    if base == "list_push":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "list_push expects 2 arguments"))
        xs = _compile_expr(ctx, state, call.args[0])
        v = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_list_push")
        out = b.call(fn, [_as_any_i64(xs, call.args[0]), _as_any_i64(v, call.args[1])])
        return _Value(out, "Int")

    if base == "list_get":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "list_get expects 2 arguments"))
        xs = _compile_expr(ctx, state, call.args[0])
        idx = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_list_get")
        out = b.call(fn, [_as_any_i64(xs, call.args[0]), _as_i64(idx, call.args[1])])
        return _Value(out, "Any")

    if base == "list_set":
        if len(call.args) != 3:
            raise CodegenError(_diag(call, "list_set expects 3 arguments"))
        xs = _compile_expr(ctx, state, call.args[0])
        idx = _compile_expr(ctx, state, call.args[1])
        v = _compile_expr(ctx, state, call.args[2])
        fn = _declare_runtime(ctx, "astra_list_set")
        out = b.call(
            fn,
            [_as_any_i64(xs, call.args[0]), _as_i64(idx, call.args[1]), _as_any_i64(v, call.args[2])],
        )
        return _Value(out, "Int")

    if base == "list_len":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "list_len expects 1 argument"))
        xs = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_list_len")
        out = b.call(fn, [_as_any_i64(xs, call.args[0])])
        return _Value(out, "Int")

    if base == "map_new":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "map_new expects 0 arguments"))
        fn = _declare_runtime(ctx, "astra_map_new")
        return _Value(b.call(fn, []), "Any")

    if base == "map_has":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "map_has expects 2 arguments"))
        m = _compile_expr(ctx, state, call.args[0])
        k = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_map_has")
        out = b.call(fn, [_as_any_i64(m, call.args[0]), _as_any_i64(k, call.args[1])])
        return _Value(out, "Bool")

    if base == "map_get":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "map_get expects 2 arguments"))
        m = _compile_expr(ctx, state, call.args[0])
        k = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_map_get")
        out = b.call(fn, [_as_any_i64(m, call.args[0]), _as_any_i64(k, call.args[1])])
        return _Value(out, "Any")

    if base == "map_set":
        if len(call.args) != 3:
            raise CodegenError(_diag(call, "map_set expects 3 arguments"))
        m = _compile_expr(ctx, state, call.args[0])
        k = _compile_expr(ctx, state, call.args[1])
        v = _compile_expr(ctx, state, call.args[2])
        fn = _declare_runtime(ctx, "astra_map_set")
        out = b.call(
            fn,
            [_as_any_i64(m, call.args[0]), _as_any_i64(k, call.args[1]), _as_any_i64(v, call.args[2])],
        )
        return _Value(out, "Int")

    if base == "mutex_new":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "mutex_new expects 0 arguments"))
        fn = _declare_runtime(ctx, "astra_mutex_new")
        return _Value(b.call(fn, []), "Int")

    if base == "mutex_lock":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "mutex_lock expects 2 arguments"))
        m = _compile_expr(ctx, state, call.args[0])
        tid = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_mutex_lock")
        out = b.call(fn, [_as_i64(m, call.args[0]), _as_i64(tid, call.args[1])])
        return _Value(out, "Int")

    if base == "mutex_unlock":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "mutex_unlock expects 2 arguments"))
        m = _compile_expr(ctx, state, call.args[0])
        tid = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_mutex_unlock")
        out = b.call(fn, [_as_i64(m, call.args[0]), _as_i64(tid, call.args[1])])
        return _Value(out, "Int")

    if base == "chan_new":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "chan_new expects 0 arguments"))
        fn = _declare_runtime(ctx, "astra_chan_new")
        return _Value(b.call(fn, []), "Int")

    if base == "chan_send":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "chan_send expects 2 arguments"))
        cid = _compile_expr(ctx, state, call.args[0])
        v = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_chan_send")
        out = b.call(fn, [_as_i64(cid, call.args[0]), _as_any_i64(v, call.args[1])])
        return _Value(out, "Int")

    if base == "chan_recv_try":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "chan_recv_try expects 1 argument"))
        cid = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_chan_recv_try")
        out_any = b.call(fn, [_as_i64(cid, call.args[0])])
        is_none_fn = _declare_runtime(ctx, "astra_any_is_none")
        is_none = b.call(is_none_fn, [out_any])
        fn_ir = state.fn_ir
        none_block = fn_ir.append_basic_block("chan_try_none")
        some_block = fn_ir.append_basic_block("chan_try_some")
        end_block = fn_ir.append_basic_block("chan_try_end")
        b.cbranch(is_none, none_block, some_block)

        i64 = ir.IntType(64)
        b.position_at_end(none_block)
        none_val = ir.Constant(ir.IntType(8).as_pointer(), None)
        b.branch(end_block)
        none_block = b.block

        b.position_at_end(some_block)
        mem = _alloc_bytes(ctx, state, ir.Constant(i64, 8), ir.Constant(i64, 8), call)
        any_ptr = b.bitcast(mem, i64.as_pointer())
        b.store(out_any, any_ptr)
        some_val = mem if mem.type == ir.IntType(8).as_pointer() else b.bitcast(mem, ir.IntType(8).as_pointer())
        b.branch(end_block)
        some_block = b.block

        b.position_at_end(end_block)
        out = b.phi(ir.IntType(8).as_pointer())
        out.add_incoming(none_val, none_block)
        out.add_incoming(some_val, some_block)
        return _Value(out, "Any?")

    if base == "chan_recv_blocking":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "chan_recv_blocking expects 1 argument"))
        cid = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_chan_recv_blocking")
        out = b.call(fn, [_as_i64(cid, call.args[0])])
        return _Value(out, "Any")

    if base == "chan_close":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "chan_close expects 1 argument"))
        cid = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_chan_close")
        out = b.call(fn, [_as_i64(cid, call.args[0])])
        return _Value(out, "Int")

    if base == "file_exists":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "file_exists expects 1 argument"))
        p = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_file_exists")
        out = b.call(fn, [_as_string_ptr(p, call.args[0])])
        return _Value(out, "Bool")

    if base == "file_remove":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "file_remove expects 1 argument"))
        p = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_file_remove")
        out = b.call(fn, [_as_string_ptr(p, call.args[0])])
        return _Value(out, "Int")

    if base == "tcp_connect":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "tcp_connect expects 1 argument"))
        a = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_tcp_connect")
        out = b.call(fn, [_as_string_ptr(a, call.args[0])])
        return _Value(out, "Int")

    if base == "tcp_send":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "tcp_send expects 2 arguments"))
        sid = _compile_expr(ctx, state, call.args[0])
        d = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_tcp_send")
        out = b.call(fn, [_as_i64(sid, call.args[0]), _as_string_ptr(d, call.args[1])])
        return _Value(out, "Int")

    if base == "tcp_recv":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "tcp_recv expects 2 arguments"))
        sid = _compile_expr(ctx, state, call.args[0])
        n = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_tcp_recv")
        out = b.call(fn, [_as_i64(sid, call.args[0]), _as_i64(n, call.args[1])])
        return _Value(out, "String")

    if base == "tcp_close":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "tcp_close expects 1 argument"))
        sid = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_tcp_close")
        out = b.call(fn, [_as_i64(sid, call.args[0])])
        return _Value(out, "Int")

    if base == "to_json":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "to_json expects 1 argument"))
        v = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_to_json")
        out = b.call(fn, [_as_any_i64(v, call.args[0])])
        return _Value(out, "String")

    if base == "from_json":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "from_json expects 1 argument"))
        s = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_from_json")
        out = b.call(fn, [_as_string_ptr(s, call.args[0])])
        return _Value(out, "Any")

    if base == "sha256":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "sha256 expects 1 argument"))
        s = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_sha256")
        out = b.call(fn, [_as_string_ptr(s, call.args[0])])
        return _Value(out, "String")

    if base == "hmac_sha256":
        if len(call.args) != 2:
            raise CodegenError(_diag(call, "hmac_sha256 expects 2 arguments"))
        k = _compile_expr(ctx, state, call.args[0])
        s = _compile_expr(ctx, state, call.args[1])
        fn = _declare_runtime(ctx, "astra_hmac_sha256")
        out = b.call(fn, [_as_string_ptr(k, call.args[0]), _as_string_ptr(s, call.args[1])])
        return _Value(out, "String")

    if base == "rand_bytes":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "rand_bytes expects 1 argument"))
        n = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_rand_bytes")
        out = b.call(fn, [_as_i64(n, call.args[0])])
        return _Value(out, "Any")

    if base == "env_get":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "env_get expects 1 argument"))
        k = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_env_get")
        out = b.call(fn, [_as_string_ptr(k, call.args[0])])
        return _Value(out, "String")

    if base == "cwd":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "cwd expects 0 arguments"))
        fn = _declare_runtime(ctx, "astra_cwd")
        out = b.call(fn, [])
        return _Value(out, "String")

    if base == "proc_run":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "proc_run expects 1 argument"))
        c = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_proc_run")
        out = b.call(fn, [_as_string_ptr(c, call.args[0])])
        return _Value(out, "Int")

    if base == "now_unix":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "now_unix expects 0 arguments"))
        fn = _declare_runtime(ctx, "astra_now_unix")
        out = b.call(fn, [])
        return _Value(out, "Int")

    if base == "monotonic_ms":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "monotonic_ms expects 0 arguments"))
        fn = _declare_runtime(ctx, "astra_monotonic_ms")
        out = b.call(fn, [])
        return _Value(out, "Int")

    if base == "sleep_ms":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "sleep_ms expects 1 argument"))
        ms = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_sleep_ms")
        out = b.call(fn, [_as_i64(ms, call.args[0])])
        return _Value(out, "Int")

    if base == "panic":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "panic expects 1 argument"))
        arg_node = call.args[0]
        if isinstance(arg_node, Literal) and isinstance(arg_node.value, str):
            g = _get_string_global(ctx, arg_node.value)
            ptr = b.gep(g, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
            l = ir.Constant(i64, len(arg_node.value.encode("utf-8")))
        else:
            a = _compile_expr(ctx, state, arg_node)
            ptr = _as_string_ptr(a, arg_node)
            l = ir.Constant(i64, 0)
        fn = _declare_runtime(ctx, "astra_panic")
        b.call(fn, [ptr, l])
        b.unreachable()
        return _Value(ir.Constant(i64, 0), "Never")

    if base == "proc_exit":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "proc_exit expects 1 argument"))
        a = _compile_expr(ctx, state, call.args[0])
        code = _coerce_value(ctx, state, a.value, a.ty, "Int", call)
        exit_fn = ctx.fn_map.get("exit")
        if not isinstance(exit_fn, ir.Function):
            exit_fn = ir.Function(ctx.module, ir.FunctionType(ir.VoidType(), [ir.IntType(32)]), name="exit")
            ctx.fn_map["exit"] = exit_fn
        b.call(exit_fn, [b.trunc(code, ir.IntType(32))])
        b.unreachable()
        return _Value(ir.Constant(i64, 0), "Never")

    if base in {"countOnes", "leadingZeros", "trailingZeros", "popcnt", "clz", "ctz"}:
        op = {
            "countOnes": "countOnes",
            "popcnt": "countOnes",
            "leadingZeros": "leadingZeros",
            "clz": "leadingZeros",
            "trailingZeros": "trailingZeros",
            "ctz": "trailingZeros",
        }[base]
        return _lower_count_like(ctx, state, call, op)

    if base in {"rotl", "rotr"}:
        return _lower_rotate(ctx, state, call, left=(base == "rotl"), overflow_mode=overflow_mode)

    if base == "await_result":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "await_result expects 1 argument"))
        return _compile_expr(ctx, state, call.args[0])

    raise CodegenError(_diag(call, f"internal: unexpected builtin dispatch {base}"))


def _compile_struct_init(
    ctx: _ModuleCtx,
    state: _FnState,
    struct_name: str,
    field_exprs: dict[str, Any],
    node: Any,
    overflow_mode: str,
) -> _Value:
    sinfo = ctx.structs.get(struct_name)
    if sinfo is None:
        raise CodegenError(_diag(node, f"unknown struct {struct_name}"))
    declared_fields = {fname for fname, _ in sinfo.decl.fields}
    for fname in field_exprs:
        if fname not in declared_fields:
            raise CodegenError(_diag(node, f"unknown field {fname} for struct {struct_name}"))
    for fname, _ in sinfo.decl.fields:
        if fname not in field_exprs:
            raise CodegenError(_diag(node, f"missing field {fname} for struct {struct_name}"))
    size, align = _storage_size_align(ctx, struct_name, node)
    ptr_i8 = _alloc_bytes(
        ctx,
        state,
        ir.Constant(ir.IntType(64), size),
        ir.Constant(ir.IntType(64), align),
        node,
        stack_ok=True,
    )
    ptr = state.builder.bitcast(ptr_i8, sinfo.ty.as_pointer())
    for i, ((fname, _), fty) in enumerate(zip(sinfo.decl.fields, sinfo.field_types)):
        arg_node = field_exprs[fname]
        a = _compile_expr(ctx, state, arg_node, overflow_mode=overflow_mode)
        cv = _coerce_value(ctx, state, a.value, a.ty, fty, arg_node)
        if sinfo.packed:
            _packed_store_bits(ctx, state, ptr, sinfo, fname, cv, node)
        else:
            fld = state.builder.gep(ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
            state.builder.store(cv, fld)
    return _Value(ptr, struct_name)


def _compile_call(ctx: _ModuleCtx, state: _FnState, call: Call, overflow_mode: str) -> _Value:
    b = state.builder
    ufcs_receiver = getattr(call, "ufcs_receiver", None)
    if ufcs_receiver is not None:
        if call.resolved_name:
            target_name = call.resolved_name
        elif isinstance(call.fn, Name):
            target_name = call.fn.value
        elif isinstance(call.fn, FieldExpr):
            target_name = call.fn.field
        else:
            raise CodegenError(_diag(call, "cannot resolve UFCS call target"))
        synthetic = Call(
            fn=Name(target_name, call.pos, call.line, call.col),
            args=[ufcs_receiver] + list(call.args),
            pos=call.pos,
            line=call.line,
            col=call.col,
            resolved_name=call.resolved_name,
        )
        setattr(synthetic, "inferred_type", getattr(call, "inferred_type", None))
        mono_symbol = getattr(call, "monomorph_symbol", None)
        if isinstance(mono_symbol, str) and mono_symbol:
            setattr(synthetic, "monomorph_symbol", mono_symbol)
        return _compile_call(ctx, state, synthetic, overflow_mode)

    if (
        isinstance(call.fn, FieldExpr)
        and isinstance(call.fn.obj, Name)
        and call.fn.obj.value == "Result"
        and call.fn.field in {"Ok", "Err"}
    ):
        if len(call.args) != 1:
            raise CodegenError(_diag(call, f"Result.{call.fn.field} expects 1 argument"))
        out_ty = _expr_type(state, call)
        parsed = _result_inner_types(out_ty)
        if parsed is None:
            raise CodegenError(_diag(call, f"Result constructor requires Result<T, E> context, got {out_ty}"))
        ok_ty, err_ty = parsed
        arg = _compile_expr(ctx, state, call.args[0], overflow_mode=overflow_mode)
        if call.fn.field == "Ok":
            payload = _coerce_value(ctx, state, arg.value, arg.ty, ok_ty, call.args[0])
            out_ptr = _emit_result_value(
                ctx,
                state,
                out_ty,
                is_ok=True,
                payload_v=payload,
                payload_ty=ok_ty,
                node=call,
            )
        else:
            payload = _coerce_value(ctx, state, arg.value, arg.ty, err_ty, call.args[0])
            out_ptr = _emit_result_value(
                ctx,
                state,
                out_ty,
                is_ok=False,
                payload_v=payload,
                payload_ty=err_ty,
                node=call,
            )
        return _Value(out_ptr, out_ty)

    if isinstance(call.fn, FieldExpr) and call.fn.field == "get":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "get expects 1 argument"))
        elem_ty, _, idx64, ln, data_ptr = _compile_index_base(
            ctx,
            state,
            call.fn.obj,
            call.args[0],
            overflow_mode,
            call,
        )
        b = state.builder
        fn_ir = state.fn_ir
        zero = ir.Constant(ir.IntType(64), 0)
        nonneg = b.icmp_signed(">=", idx64, zero)
        lt = b.icmp_signed("<", idx64, ln)
        in_bounds = b.and_(nonneg, lt)
        some_block = fn_ir.append_basic_block("get_some")
        none_block = fn_ir.append_basic_block("get_none")
        end_block = fn_ir.append_basic_block("get_end")
        b.cbranch(in_bounds, some_block, none_block)

        b.position_at_end(some_block)
        elem_ptr = b.gep(data_ptr, [idx64])
        some_val = _as_i8_ptr(state, elem_ptr, call)
        b.branch(end_block)
        some_block = b.block

        b.position_at_end(none_block)
        b.branch(end_block)
        none_block = b.block

        b.position_at_end(end_block)
        out = b.phi(ir.IntType(8).as_pointer())
        out.add_incoming(some_val, some_block)
        out.add_incoming(ir.Constant(ir.IntType(8).as_pointer(), None), none_block)
        return _Value(out, f"Option<{elem_ty}>")

    if isinstance(call.fn, Name):
        name = call.fn.value
        resolved = getattr(call, "monomorph_symbol", None) or call.resolved_name or name
        if name in ctx.structs:
            sinfo = ctx.structs[name]
            if len(call.args) != len(sinfo.field_types):
                raise CodegenError(_diag(call, f"struct {name} expects {len(sinfo.field_types)} args, got {len(call.args)}"))
            fields = {fname: arg for (fname, _), arg in zip(sinfo.decl.fields, call.args)}
            return _compile_struct_init(ctx, state, name, fields, call, overflow_mode)

        if resolved not in ctx.fn_map and resolved in {
            "print",
            "len",
            "read_file",
            "write_file",
            "args",
            "arg",
            "spawn",
            "join",
            "await_result",
            "list_new",
            "list_push",
            "list_get",
            "list_set",
            "list_len",
            "map_new",
            "map_has",
            "map_get",
            "map_set",
            "file_exists",
            "file_remove",
            "tcp_connect",
            "tcp_send",
            "tcp_recv",
            "tcp_close",
            "to_json",
            "from_json",
            "sha256",
            "hmac_sha256",
            "rand_bytes",
            "mutex_new",
            "mutex_lock",
            "mutex_unlock",
            "chan_new",
            "chan_send",
            "chan_recv_try",
            "chan_recv_blocking",
            "chan_close",
            "proc_exit",
            "env_get",
            "cwd",
            "proc_run",
            "now_unix",
            "monotonic_ms",
            "sleep_ms",
            "countOnes",
            "leadingZeros",
            "trailingZeros",
            "popcnt",
            "clz",
            "ctz",
            "rotl",
            "rotr",
            "vec_new",
            "vec_from",
            "vec_len",
            "vec_get",
            "vec_set",
            "vec_push",
            "format",
            "__format",
            "__print",
            "__len",
            "__read_file",
            "__write_file",
            "__args",
            "__arg",
            "__spawn",
            "__join",
            "__await_result",
            "__atomic_int_new",
            "__atomic_load",
            "__atomic_store",
            "__atomic_fetch_add",
            "__atomic_compare_exchange",
            "__list_new",
            "__list_push",
            "__list_get",
            "__list_set",
            "__list_len",
            "__map_new",
            "__map_has",
            "__map_get",
            "__map_set",
            "__file_exists",
            "__file_remove",
            "__tcp_connect",
            "__tcp_send",
            "__tcp_recv",
            "__tcp_close",
            "__to_json",
            "__from_json",
            "__sha256",
            "__hmac_sha256",
            "__rand_bytes",
            "__mutex_new",
            "__mutex_lock",
            "__mutex_unlock",
            "__chan_new",
            "__chan_send",
            "__chan_recv_try",
            "__chan_recv_blocking",
            "__chan_close",
            "__proc_exit",
            "__env_get",
            "__cwd",
            "__proc_run",
            "__now_unix",
            "__monotonic_ms",
            "__sleep_ms",
            "__countOnes",
            "__leadingZeros",
            "__trailingZeros",
            "__popcnt",
            "__clz",
            "__ctz",
            "__rotl",
            "__rotr",
            "__vec_new",
            "__vec_from",
            "__vec_len",
            "__vec_get",
            "__vec_set",
            "__vec_push",
            "panic",
            "__panic",
        }:
            return _compile_builtin_call(ctx, state, call, resolved, overflow_mode)

        sig = ctx.fn_sigs.get(resolved)
        callee = ctx.fn_map.get(resolved)
        call_target = resolved
        if (sig is None or not isinstance(callee, ir.Function)) and resolved in ctx.monomorph_aliases:
            alias = ctx.monomorph_aliases[resolved]
            alias_sig = ctx.fn_sigs.get(alias)
            alias_fn = ctx.fn_map.get(alias)
            if alias_sig is not None and isinstance(alias_fn, ir.Function):
                sig = alias_sig
                callee = alias_fn
                call_target = alias

        if isinstance(callee, ir.Function) and sig is not None:
            args: list[ir.Value] = []
            for arg_node, pty in zip(call.args, sig.params):
                pty_c = _canonical_type(pty)
                if (
                    pty_c.startswith("&")
                    and not (isinstance(arg_node, Unary) and arg_node.op in {"&", "&mut"})
                    and isinstance(arg_node, Name)
                    and arg_node.value in state.vars
                ):
                    inner = _strip_ref_type(pty_c)
                    actual = state.var_types.get(arg_node.value, "Any")
                    if _canonical_type(inner) == _canonical_type(actual):
                        args.append(state.vars[arg_node.value])
                        continue
                a = _compile_expr(ctx, state, arg_node)
                coerced_arg = _implicit_coerce_value(ctx, state, a.value, a.ty, pty, arg_node)
                # Keep argument values in the declared parameter type.
                # ABI extension for small integers is expressed via signext/zeroext attributes.
                args.append(coerced_arg)
            if len(call.args) != len(sig.params):
                raise CodegenError(_diag(call, f"{call_target} expects {len(sig.params)} args, got {len(call.args)}"))
            out = state.builder.call(callee, args)
            
            # Apply ABI attributes to call site for extern functions
            if sig.extern:
                _apply_abi_attributes_to_call(ctx, out, sig)
            
            ret = _canonical_type(sig.ret)
            if ret in {"Void", "Never"}:
                return _Value(ir.Constant(ir.IntType(64), 0), ret)
            return _Value(out, ret)

    # Fallback indirect call support for function pointers of known fn(...) type.
    fn_val = _compile_expr(ctx, state, call.fn)
    parsed = _parse_fn_type(fn_val.ty)
    if parsed is None:
        raise CodegenError(_diag(call, f"cannot resolve call target for {type(call.fn).__name__}: function '{call.fn.value if hasattr(call.fn, 'value') else 'unknown'}' not found in current scope"))
    param_tys, ret_ty, _ = parsed
    if len(param_tys) != len(call.args):
        raise CodegenError(_diag(call, f"callee expects {len(param_tys)} args, got {len(call.args)}"))
    fnty = ir.FunctionType(_llvm_type(ctx, ret_ty), [_llvm_type(ctx, t) for t in param_tys])
    callee_ptr = fn_val.value
    if isinstance(callee_ptr.type, ir.PointerType) and callee_ptr.type.pointee != fnty:
        callee_ptr = state.builder.bitcast(callee_ptr, fnty.as_pointer())
    args: list[ir.Value] = []
    for arg_node, pty in zip(call.args, param_tys):
        a = _compile_expr(ctx, state, arg_node)
        coerced_arg = _implicit_coerce_value(ctx, state, a.value, a.ty, pty, arg_node)
        args.append(coerced_arg)
    out = state.builder.call(callee_ptr, args)
    if _canonical_type(ret_ty) in {"Void", "Never"}:
        return _Value(ir.Constant(ir.IntType(64), 0), _canonical_type(ret_ty))
    return _Value(out, _canonical_type(ret_ty))


def _get_common_int_type(ty1: str, ty2: str) -> str:
    """Get the common integer type for two types."""
    # Simple implementation: prefer the larger type
    int_types = ["Int8", "Int16", "Int32", "Int64", "Int"]
    uint_types = ["UInt8", "UInt16", "UInt32", "UInt64"]
    
    # If both are the same, return that type
    if ty1 == ty2:
        return ty1
    
    # Handle signed vs unsigned - prefer signed for simplicity
    if ty1 in int_types and ty2 in int_types:
        # Return the one with higher rank
        if int_types.index(ty1) >= int_types.index(ty2):
            return ty1
        else:
            return ty2
    elif ty1 in uint_types and ty2 in uint_types:
        if uint_types.index(ty1) >= uint_types.index(ty2):
            return ty1
        else:
            return ty2
    else:
        # Mixed signed/unsigned, default to Int64
        return "Int64"


def _compile_expr(ctx: _ModuleCtx, state: _FnState, e: Any, overflow_mode: str = "trap") -> _Value:
    b = state.builder
    if isinstance(e, WildcardPattern):
        raise CodegenError(_diag(e, "wildcard pattern `_` is only valid in match arms"))
    if isinstance(e, OrPattern):
        raise CodegenError(_diag(e, "or-patterns are only valid in match arms"))
    if isinstance(e, GuardedPattern):
        raise CodegenError(_diag(e, "match guards are only valid in match arms"))
    if isinstance(e, RangePattern):
        raise CodegenError(_diag(e, "range patterns are only valid in match arms"))
    if isinstance(e, SlicePattern):
        raise CodegenError(_diag(e, "slice patterns are only valid in match arms"))
    if isinstance(e, TuplePattern):
        raise CodegenError(_diag(e, "tuple patterns are only valid in match arms"))
    if isinstance(e, StructPattern):
        raise CodegenError(_diag(e, "struct patterns are only valid in match arms"))
    if isinstance(e, BoolLit):
        return _Value(ir.Constant(ir.IntType(1), 1 if e.value else 0), "Bool")
    if isinstance(e, NilLit):
        return _Value(ir.Constant(ir.IntType(8).as_pointer(), None), "Option<Any>")
    if isinstance(e, Literal):
        if isinstance(e.value, bool):
            return _Value(ir.Constant(ir.IntType(1), 1 if e.value else 0), "Bool")
        if isinstance(e.value, int):
            t = _expr_type(state, e)
            llty = _llvm_type(ctx, t)
            if not isinstance(llty, ir.IntType):
                llty = ir.IntType(64)
                t = "Int"
            
            # For arbitrary integer types, mask the value to the correct bit width
            if isinstance(llty, ir.IntType) and llty.width < 64:
                bits = llty.width
                # Get type info to determine signedness
                int_info = _int_info(t)
                if int_info:
                    _, signed = int_info
                    if not signed:
                        # For unsigned types, mask to the bit width
                        masked_value = e.value & ((1 << bits) - 1)
                        return _Value(ir.Constant(llty, masked_value), t)
                    else:
                        # For signed types, ensure proper sign extension
                        # Convert to signed integer with proper range
                        min_val = -(1 << (bits - 1))
                        max_val = (1 << (bits - 1)) - 1
                        if e.value > max_val:
                            # Handle case where positive value exceeds signed range
                            # This can happen with literals like 5u3 that get treated as signed
                            # Convert to two's complement representation
                            masked_value = e.value & ((1 << bits) - 1)
                            if masked_value >= (1 << (bits - 1)):
                                # Convert to negative value for LLVM signed constant
                                signed_value = masked_value - (1 << bits)
                                return _Value(ir.Constant(llty, signed_value), t)
                        return _Value(ir.Constant(llty, int(e.value)), t)
            
            return _Value(ir.Constant(llty, int(e.value)), t)
        if isinstance(e.value, float):
            t = _expr_type(state, e)
            llty = _llvm_type(ctx, t)
            if isinstance(llty, ir.FloatType):
                return _Value(ir.Constant(llty, float(e.value)), "f32")
            return _Value(ir.Constant(ir.DoubleType(), float(e.value)), "Float")
        if isinstance(e.value, str):
            g = _get_string_global(ctx, e.value)
            ptr = b.gep(g, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
            return _Value(ptr, "String", str_len=len(e.value.encode("utf-8")))
        raise CodegenError(_diag(e, f"internal: unexpected literal type {type(e.value).__name__}"))
    if isinstance(e, Name):
        # Check all scopes for function references first
        fn = None
        sig = None
        
        # Check current module functions
        if e.value in ctx.fn_map:
            fn = ctx.fn_map[e.value]
            sig = ctx.fn_sigs.get(e.value)
        
        # Check function groups and global functions
        elif hasattr(ctx, 'fn_groups') and e.value in ctx.fn_groups:
            fn_group = ctx.fn_groups[e.value]
            if fn_group:
                fn = fn_group[0]  # Take first function from group
                sig = ctx.fn_sigs.get(e.value)
        
        if fn and sig and isinstance(fn, ir.Function):
            # Return function pointer with proper type
            fn_ty = f"fn({', '.join(sig.params)}) {sig.ret}"
            if getattr(sig, 'unsafe', False):
                fn_ty = f"unsafe {fn_ty}"
            # LLVM functions are already pointers, so use fn directly
            return _Value(fn, fn_ty)
        
        # Check local variables (existing logic)
        if e.value in state.vars:
            ptr = state.vars[e.value]
            ty = state.var_types.get(e.value, "Int")
            return _Value(b.load(ptr), ty)
        
        # Check for builtins like NaN
        if e.value == "NaN":
            # Create a NaN constant using bitcast from integer
            double_type = ir.DoubleType()
            # IEEE 754 quiet NaN pattern (0x7ff8000000000000)
            nan_bits = 0x7ff8000000000000
            nan_int = ir.Constant(ir.IntType(64), nan_bits)
            nan_val = b.bitcast(nan_int, double_type)
            return _Value(nan_val, "Float")
        
        # Function exists but not in current scope (better error message)
        if e.value in ctx.fn_sigs:
            raise CodegenError(_diag(e, f"function '{e.value}' exists but is not accessible in current scope"))
        
        raise CodegenError(_diag(e, f"undefined local or function value '{e.value}'"))
    if isinstance(e, TryExpr):
        src = _compile_expr(ctx, state, e.expr, overflow_mode=overflow_mode)
        src_ty = _canonical_type(src.ty)
        fn_ret = _canonical_type(state.ret_type)
        if _is_option_type(src_ty):
            if not _is_option_type(fn_ret):
                raise CodegenError(_diag(e, f"`?` requires Option<T> function return type, got {fn_ret}"))
            if not isinstance(src.value.type, ir.PointerType):
                raise CodegenError(_diag(e, "internal: Option<T> lowering expects pointer storage"))
            is_none = b.icmp_unsigned("==", src.value, ir.Constant(src.value.type, None))
            fn_ir = state.fn_ir
            none_block = fn_ir.append_basic_block("try_none")
            some_block = fn_ir.append_basic_block("try_some")
            b.cbranch(is_none, none_block, some_block)

            b.position_at_end(none_block)
            if state.ret_alloca is None:
                raise CodegenError(_diag(e, "internal: missing return storage for `?` propagation"))
            none_rv = _default_value(ctx, fn_ret)
            b.store(none_rv, state.ret_alloca)
            b.branch(state.epilogue_block)

            b.position_at_end(some_block)
            inner_ty = _option_inner_type(src_ty)
            inner_ll = _llvm_type(ctx, inner_ty)
            some_ptr = b.bitcast(src.value, inner_ll.as_pointer())
            some_v = b.load(some_ptr)
            return _Value(some_v, inner_ty)

        parsed_src = _result_inner_types(src_ty)
        if parsed_src is None:
            raise CodegenError(_diag(e, f"`?` expects Option<T> or Result<T, E> operand, got {src_ty}"))
        if not _is_result_type(fn_ret):
            raise CodegenError(_diag(e, f"`?` on Result<T, E> requires Result<T, E> function return type, got {fn_ret}"))
        parsed_fn = _result_inner_types(fn_ret)
        if parsed_fn is None:
            raise CodegenError(_diag(e, f"internal: malformed function return type {fn_ret}"))
        ok_ty, err_ty = parsed_src
        _, fn_err_ty = parsed_fn
        if _canonical_type(err_ty) != _canonical_type(fn_err_ty):
            raise CodegenError(
                _diag(e, f"`?` on Result<T, E> requires matching error type, got {err_ty} and {fn_err_ty}")
            )
        if not isinstance(src.value.type, ir.PointerType):
            raise CodegenError(_diag(e, "internal: Result<T, E> lowering expects pointer storage"))

        fn_ir = state.fn_ir
        is_ok_block = fn_ir.append_basic_block("try_result_ok")
        is_err_block = fn_ir.append_basic_block("try_result_err")
        res_ptr = b.bitcast(src.value, _result_storage_ty().as_pointer())
        tag_ptr = b.gep(res_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
        payload_ptr = b.gep(res_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
        tag = b.load(tag_ptr)
        ok_cond = b.icmp_unsigned("==", tag, ir.Constant(ir.IntType(8), 1))
        b.cbranch(ok_cond, is_ok_block, is_err_block)

        b.position_at_end(is_err_block)
        if state.ret_alloca is None:
            raise CodegenError(_diag(e, "internal: missing return storage for `?` propagation"))
        err_any = b.load(payload_ptr)
        err_value = _coerce_value(ctx, state, err_any, "Any", fn_err_ty, e)
        err_result = _emit_result_value(
            ctx,
            state,
            fn_ret,
            is_ok=False,
            payload_v=err_value,
            payload_ty=fn_err_ty,
            node=e,
        )
        b.store(err_result, state.ret_alloca)
        b.branch(state.epilogue_block)

        b.position_at_end(is_ok_block)
        ok_any = b.load(payload_ptr)
        ok_value = _coerce_value(ctx, state, ok_any, "Any", ok_ty, e)
        return _Value(ok_value, ok_ty)
    if isinstance(e, AwaitExpr):
        return _compile_expr(ctx, state, e.expr, overflow_mode=overflow_mode)
    if isinstance(e, CastExpr):
        dst_ty = _canonical_type(e.type_name)
        
        # Optimize: Cast from integer literal to integer type - create target type constant directly
        if isinstance(e.expr, Literal) and isinstance(e.expr.value, int):
            int_info = _int_info(dst_ty)
            if int_info is not None:
                bits, signed = int_info
                # Create constant with target type directly, avoiding i64->target truncation
                target_llty = ir.IntType(bits)
                literal_value = e.expr.value
                
                
                if not signed:
                    # For unsigned types, mask to the bit width
                    masked_value = literal_value & ((1 << bits) - 1)
                    print(f"  -> creating unsigned constant: ir.Constant({target_llty}, {masked_value})")
                    result = _Value(ir.Constant(target_llty, masked_value), dst_ty)
                    print(f"  -> result constant: {result.value}")
                    return result
                else:
                    # For signed types, check range and handle overflow
                    min_val = -(1 << (bits - 1))
                    max_val = (1 << (bits - 1)) - 1
                    if literal_value > max_val:
                        # Convert to two's complement representation
                        masked_value = literal_value & ((1 << bits) - 1)
                        if masked_value >= (1 << (bits - 1)):
                            # Convert to negative value for LLVM signed constant
                            signed_value = masked_value - (1 << bits)
                            return _Value(ir.Constant(target_llty, signed_value), dst_ty)
                    return _Value(ir.Constant(target_llty, literal_value), dst_ty)
        
        if isinstance(e.expr, Call) and isinstance(e.expr.fn, Name):
            base = e.expr.fn.value[2:] if e.expr.fn.value.startswith("__") else e.expr.fn.value
            if _is_vec_type(dst_ty) and base in {"vec_new", "vec_from"}:
                had_prev = hasattr(e.expr, "inferred_type")
                prev = getattr(e.expr, "inferred_type", None)
                setattr(e.expr, "inferred_type", dst_ty)
                try:
                    src = _compile_expr(ctx, state, e.expr, overflow_mode=overflow_mode)
                finally:
                    if not had_prev:
                        delattr(e.expr, "inferred_type")
                    else:
                        setattr(e.expr, "inferred_type", prev)
                cv = _explicit_cast_value(ctx, state, src.value, src.ty, dst_ty, e)
                return _Value(cv, dst_ty)
        src = _compile_expr(ctx, state, e.expr, overflow_mode=overflow_mode)
        cv = _explicit_cast_value(ctx, state, src.value, src.ty, dst_ty, e)
        return _Value(cv, dst_ty)
    if isinstance(e, Unary):
        if e.op in {"&", "&mut"}:
            if not isinstance(e.expr, Name) or e.expr.value not in state.vars:
                raise CodegenError(_diag(e, "borrow expressions require local names"))
            ptr = state.vars[e.expr.value]
            inner = state.var_types.get(e.expr.value, "Int")
            return _Value(ptr, f"&mut {inner}" if e.op == "&mut" else f"&{inner}")
        inner = _compile_expr(ctx, state, e.expr, overflow_mode=overflow_mode)
        if e.op == "*":
            if not isinstance(inner.value.type, ir.PointerType):
                raise CodegenError(_diag(e, f"cannot dereference non-pointer type {inner.ty}"))
            out_ty = _expr_type(state, e)
            return _Value(b.load(inner.value), out_ty)
        if e.op == "-":
            if isinstance(inner.value.type, (ir.FloatType, ir.DoubleType)):
                return _Value(b.fsub(ir.Constant(inner.value.type, 0.0), inner.value), inner.ty)
            return _Value(b.sub(ir.Constant(inner.value.type, 0), inner.value), inner.ty)
        if e.op == "!":
            if isinstance(inner.value.type, ir.IntType):
                if inner.value.type.width == 1:
                    return _Value(b.xor(inner.value, ir.Constant(ir.IntType(1), 1)), "Bool")
                zero = ir.Constant(inner.value.type, 0)
                return _Value(b.icmp_unsigned("==", inner.value, zero), "Bool")
            raise CodegenError(_diag(e, "unary ! expects integer/bool"))
        if e.op == "~":
            if not isinstance(inner.value.type, ir.IntType):
                raise CodegenError(_diag(e, "unary ~ expects integer"))
            all_ones = ir.Constant(inner.value.type, (1 << inner.value.type.width) - 1)
            return _Value(b.xor(inner.value, all_ones), inner.ty)
        raise CodegenError(_diag(e, f"internal: unexpected unary op {e.op}"))
    if isinstance(e, RangeExpr):
        # Compile range expressions as a struct with start and end fields
        start_val = _compile_expr(ctx, state, e.start, overflow_mode=overflow_mode)
        end_val = _compile_expr(ctx, state, e.end, overflow_mode=overflow_mode)
        
        # Ensure both bounds are the same integer type
        if start_val.ty != end_val.ty:
            # Coerce to common type
            common_ty = _get_common_int_type(start_val.ty, end_val.ty)
            start_val = _coerce_value(ctx, state, start_val.value, start_val.ty, common_ty, e.start)
            end_val = _coerce_value(ctx, state, end_val.value, end_val.ty, common_ty, e.end)
        
        # Create a range struct type
        range_fields = [
            _llvm_type(ctx, start_val.ty),  # start
            _llvm_type(ctx, end_val.ty),    # end
            ir.IntType(1),                  # inclusive flag
        ]
        range_struct_type = ir.LiteralStructType(range_fields)
        
        # Create the range struct value
        inclusive_val = ir.Constant(ir.IntType(1), 1 if e.inclusive else 0)
        range_val = ir.Constant(range_struct_type, [
            start_val.value,
            end_val.value,
            inclusive_val
        ])
        
        range_ty = f"Range[{start_val.ty}]"
        if e.inclusive:
            range_ty = f"RangeInclusive[{start_val.ty}]"
        
        return _Value(range_val, range_ty)
    if isinstance(e, Binary):
        if e.op in {"&&", "||"}:
            left = _compile_expr(ctx, state, e.left, overflow_mode=overflow_mode)
            lbool = _coerce_value(ctx, state, left.value, left.ty, "Bool", e.left)
            fn_ir = state.fn_ir
            rhs_block = fn_ir.append_basic_block("logic_rhs")
            short_block = fn_ir.append_basic_block("logic_short")
            end_block = fn_ir.append_basic_block("logic_end")
            if e.op == "&&":
                b.cbranch(lbool, rhs_block, short_block)
                short_val = ir.Constant(ir.IntType(1), 0)
            else:
                b.cbranch(lbool, short_block, rhs_block)
                short_val = ir.Constant(ir.IntType(1), 1)

            b.position_at_end(short_block)
            b.branch(end_block)
            short_block = b.block

            b.position_at_end(rhs_block)
            right = _compile_expr(ctx, state, e.right, overflow_mode=overflow_mode)
            rbool = _coerce_value(ctx, state, right.value, right.ty, "Bool", e.right)
            rhs_pred: ir.Block | None = None
            if not _is_terminated(state):
                b.branch(end_block)
                rhs_pred = b.block

            b.position_at_end(end_block)
            if rhs_pred is None:
                return _Value(short_val, "Bool")
            out = b.phi(ir.IntType(1))
            out.add_incoming(short_val, short_block)
            out.add_incoming(rbool, rhs_pred)
            return _Value(out, "Bool")
        if e.op == "??":
            left = _compile_expr(ctx, state, e.left, overflow_mode=overflow_mode)
            if not isinstance(left.value.type, ir.PointerType):
                right = _compile_expr(ctx, state, e.right, overflow_mode=overflow_mode)
                return right
            if not _is_option_type(left.ty):
                right = _compile_expr(ctx, state, e.right, overflow_mode=overflow_mode)
                return right
            out_ty = _canonical_type(getattr(e, "inferred_type", _option_inner_type(left.ty)))
            out_ll = _llvm_type(ctx, out_ty)
            is_none = b.icmp_unsigned("==", left.value, ir.Constant(left.value.type, None))
            fn_ir = state.fn_ir
            none_block = fn_ir.append_basic_block("coalesce_none")
            some_block = fn_ir.append_basic_block("coalesce_some")
            end_block = fn_ir.append_basic_block("coalesce_end")
            b.cbranch(is_none, none_block, some_block)

            b.position_at_end(none_block)
            right = _compile_expr(ctx, state, e.right, overflow_mode=overflow_mode)
            right_v = _coerce_value(ctx, state, right.value, right.ty, out_ty, e.right)
            none_pred: ir.Block | None = None
            if not _is_terminated(state):
                b.branch(end_block)
                none_pred = b.block

            b.position_at_end(some_block)
            some_ptr = b.bitcast(left.value, out_ll.as_pointer())
            some_v = b.load(some_ptr)
            b.branch(end_block)
            some_block = b.block

            b.position_at_end(end_block)
            if none_pred is None:
                return _Value(some_v, out_ty)
            out = b.phi(out_ll)
            out.add_incoming(right_v, none_pred)
            out.add_incoming(some_v, some_block)
            return _Value(out, out_ty)

        left = _compile_expr(ctx, state, e.left, overflow_mode=overflow_mode)
        right = _compile_expr(ctx, state, e.right, overflow_mode=overflow_mode)
        if e.op == "+" and _is_text_type(left.ty) and _is_text_type(right.ty):
            lsp = _coerce_value(ctx, state, left.value, left.ty, "String", e.left)
            rsp = _coerce_value(ctx, state, right.value, right.ty, "String", e.right)
            fn = _declare_runtime(ctx, "astra_str_concat")
            out = b.call(fn, [lsp, rsp])
            return _Value(out, "String")
        ty = _expr_type(state, e.left)

        if _is_float_type(ty):
            lv = _coerce_value(ctx, state, left.value, left.ty, ty, e.left)
            rv = _coerce_value(ctx, state, right.value, right.ty, ty, e.right)
            if e.op == "+":
                return _Value(b.fadd(lv, rv), ty)
            if e.op == "-":
                return _Value(b.fsub(lv, rv), ty)
            if e.op == "*":
                return _Value(b.fmul(lv, rv), ty)
            if e.op == "/":
                return _Value(b.fdiv(lv, rv), ty)
            if e.op == "%":
                return _Value(b.frem(lv, rv), ty)
            if e.op in {"==", "!=", "<", "<=", ">", ">="}:
                pred = {
                    "==": "==",
                    "!=": "!=",
                    "<": "<",
                    "<=": "<=",
                    ">": ">",
                    ">=": ">=",
                }[e.op]
                return _Value(b.fcmp_ordered(pred, lv, rv), "Bool")
            raise CodegenError(_diag(e, f"internal: unexpected float binary op {e.op}"))

        info = _int_info(ty)
        lty = ty
        if info is None:
            lty = "Int"
            info = _int_info(lty)
        bits, signed = info
        lv = _coerce_value(ctx, state, left.value, left.ty, lty, e.left)
        rv = _coerce_value(ctx, state, right.value, right.ty, lty, e.right)

        if bits == 128 and e.op in {"*", "/", "%"} and not ctx.freestanding:
            sym = _i128_helper_symbol({"*": "mul", "/": "div", "%": "mod"}[e.op], signed, overflow_mode)
            fn = _declare_runtime(ctx, sym)
            out = b.call(fn, [lv, rv])
            return _Value(out, lty)

        if e.op == "+":
            if overflow_mode == "trap":
                # Use overflow intrinsic with conditional branch (standard LLVM pattern)
                intrinsic = f"llvm.{'u' if not signed else 's'}add.with.overflow.i{bits}"
                
                # Create or get the overflow intrinsic function
                if intrinsic not in ctx.fn_map:
                    # Create the struct type for overflow result: {iN, i1}
                    result_type = ir.LiteralStructType([ir.IntType(bits), ir.IntType(1)])
                    # Overflow intrinsics take both operands as parameters
                    fn_type = ir.FunctionType(result_type, [ir.IntType(bits), ir.IntType(bits)])
                    fn = ir.Function(ctx.module, fn_type, name=intrinsic)
                    ctx.fn_map[intrinsic] = fn
                else:
                    fn = ctx.fn_map[intrinsic]
                
                result = b.call(fn, [lv, rv])
                
                # Extract result and overflow flag
                actual_result = b.extract_value(result, 0)
                overflow_flag = b.extract_value(result, 1)
                
                # Create basic blocks for conditional branch
                current_fn = state.builder.basic_block.function
                trap_block = current_fn.append_basic_block("overflow_trap")
                ok_block = current_fn.append_basic_block("overflow_ok")
                
                # Conditional branch on overflow flag
                b.cbranch(overflow_flag, trap_block, ok_block)
                
                # Trap block: call llvm.trap and mark unreachable
                b.position_at_end(trap_block)
                trap_fn = _declare_trap(ctx)
                b.call(trap_fn, [])
                b.unreachable()
                
                # OK block: continue with actual result
                b.position_at_end(ok_block)
                return _Value(actual_result, lty)
            else:
                # Release mode - plain arithmetic (LLVM wraps automatically)
                return _Value(b.add(lv, rv), lty)
        if e.op == "-":
            if overflow_mode == "trap":
                # Use overflow intrinsic with conditional branch
                intrinsic = f"llvm.{'u' if not signed else 's'}sub.with.overflow.i{bits}"
                
                # Create or get the overflow intrinsic function
                if intrinsic not in ctx.fn_map:
                    # Create the struct type for overflow result: {iN, i1}
                    result_type = ir.LiteralStructType([ir.IntType(bits), ir.IntType(1)])
                    # Overflow intrinsics take both operands as parameters
                    fn_type = ir.FunctionType(result_type, [ir.IntType(bits), ir.IntType(bits)])
                    fn = ir.Function(ctx.module, fn_type, name=intrinsic)
                    ctx.fn_map[intrinsic] = fn
                else:
                    fn = ctx.fn_map[intrinsic]
                
                result = b.call(fn, [lv, rv])
                
                # Extract result and overflow flag
                actual_result = b.extract_value(result, 0)
                overflow_flag = b.extract_value(result, 1)
                
                # Create basic blocks for conditional branch
                current_fn = state.builder.basic_block.function
                trap_block = current_fn.append_basic_block("overflow_trap")
                ok_block = current_fn.append_basic_block("overflow_ok")
                
                # Conditional branch on overflow flag
                b.cbranch(overflow_flag, trap_block, ok_block)
                
                # Trap block: call llvm.trap and mark unreachable
                b.position_at_end(trap_block)
                trap_fn = _declare_trap(ctx)
                b.call(trap_fn, [])
                b.unreachable()
                
                # OK block: continue with actual result
                b.position_at_end(ok_block)
                return _Value(actual_result, lty)
            else:
                # Release mode - plain arithmetic (LLVM wraps automatically)
                return _Value(b.sub(lv, rv), lty)
        if e.op == "*":
            if overflow_mode == "trap":
                # Use overflow intrinsic with conditional branch
                intrinsic = f"llvm.{'u' if not signed else 's'}mul.with.overflow.i{bits}"
                
                # Create or get the overflow intrinsic function
                if intrinsic not in ctx.fn_map:
                    # Create the struct type for overflow result: {iN, i1}
                    result_type = ir.LiteralStructType([ir.IntType(bits), ir.IntType(1)])
                    # Overflow intrinsics take both operands as parameters
                    fn_type = ir.FunctionType(result_type, [ir.IntType(bits), ir.IntType(bits)])
                    fn = ir.Function(ctx.module, fn_type, name=intrinsic)
                    ctx.fn_map[intrinsic] = fn
                else:
                    fn = ctx.fn_map[intrinsic]
                
                result = b.call(fn, [lv, rv])
                
                # Extract result and overflow flag
                actual_result = b.extract_value(result, 0)
                overflow_flag = b.extract_value(result, 1)
                
                # Create basic blocks for conditional branch
                current_fn = state.builder.basic_block.function
                trap_block = current_fn.append_basic_block("overflow_trap")
                ok_block = current_fn.append_basic_block("overflow_ok")
                
                # Conditional branch on overflow flag
                b.cbranch(overflow_flag, trap_block, ok_block)
                
                # Trap block: call llvm.trap and mark unreachable
                b.position_at_end(trap_block)
                trap_fn = _declare_trap(ctx)
                b.call(trap_fn, [])
                b.unreachable()
                
                # OK block: continue with actual result
                b.position_at_end(ok_block)
                return _Value(actual_result, lty)
            else:
                # Release mode - plain arithmetic (LLVM wraps automatically)
                return _Value(b.mul(lv, rv), lty)
        if e.op == "/":
            return _Value(_lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=True), lty)
        if e.op == "%":
            return _Value(_lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=False), lty)
        if e.op == "&":
            return _Value(b.and_(lv, rv), lty)
        if e.op == "|":
            return _Value(b.or_(lv, rv), lty)
        if e.op == "^":
            return _Value(b.xor(lv, rv), lty)
        if e.op == "<<":
            return _Value(_lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=True), lty)
        if e.op == ">>":
            return _Value(_lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=False), lty)
        if e.op in {"==", "!=", "<", "<=", ">", ">="}:
            if e.op in {"==", "!="}:
                pred = e.op
                cmpv = b.icmp_unsigned(pred, lv, rv)
            elif signed:
                pred = {"<": "<", "<=": "<=", ">": ">", ">=": ">="}[e.op]
                cmpv = b.icmp_signed(pred, lv, rv)
            else:
                pred = {"<": "<", "<=": "<=", ">": ">", ">=": ">="}[e.op]
                cmpv = b.icmp_unsigned(pred, lv, rv)
            return _Value(cmpv, "Bool")
        raise CodegenError(_diag(e, f"internal: unexpected binary op {e.op}"))
    if isinstance(e, Call):
        return _compile_call(ctx, state, e, overflow_mode=overflow_mode)
    if isinstance(e, FieldExpr):
        obj = _compile_expr(ctx, state, e.obj, overflow_mode=overflow_mode)
        obj_ty = _expr_type(state, e.obj)
        base_ty = _strip_ref_type(obj_ty)

        if base_ty not in ctx.structs:
            raise CodegenError(_diag(e, f"field access requires struct receiver, got {base_ty}"))
        sinfo = ctx.structs[base_ty]
        idx = sinfo.field_index.get(e.field)
        if idx is None:
            raise CodegenError(_diag(e, f"unknown field {e.field} on {base_ty}"))
        ptr = _struct_ptr(ctx, state, obj.value, obj_ty, sinfo, e)
        fty = sinfo.field_types[idx]
        if sinfo.packed:
            raw, bits, _ = _packed_load_bits(ctx, state, ptr, sinfo, e.field, e)
            ll = _llvm_type(ctx, fty)
            if not isinstance(ll, ir.IntType):
                raise CodegenError(_diag(e, f"packed field {e.field} must be integer/bool"))
            field_ll = ir.IntType(bits)
            raw_field = raw
            if raw_field.type.width != bits:
                if raw_field.type.width > bits:
                    raw_field = b.trunc(raw_field, field_ll)
                else:
                    raw_field = b.zext(raw_field, field_ll)
            if ll.width > bits:
                if _is_signed_int(fty):
                    val = b.sext(raw_field, ll)
                else:
                    val = b.zext(raw_field, ll)
            elif ll.width < bits:
                val = b.trunc(raw_field, ll)
            else:
                val = raw_field
            return _Value(val, fty)
        fld = b.gep(ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), idx)])
        return _Value(b.load(fld), fty)
    if isinstance(e, StructLit):
        field_map: dict[str, Any] = {}
        for fname, fexpr in e.fields:
            if fname in field_map:
                raise CodegenError(_diag(e, f"duplicate field {fname} in struct literal {e.name}"))
            field_map[fname] = fexpr
        return _compile_struct_init(ctx, state, e.name, field_map, e, overflow_mode)
    if isinstance(e, TypeAnnotated):
        inner = _compile_expr(ctx, state, e.expr, overflow_mode=overflow_mode)
        return _Value(_coerce_value(ctx, state, inner.value, inner.ty, _canonical_type(e.type_name), e), _canonical_type(e.type_name))
    if isinstance(e, SizeOfTypeExpr):
        q = _canonical_type(getattr(e, "query_type", e.type_name))
        lay = _query_layout(ctx, q, e)
        return _Value(ir.Constant(ir.IntType(64), lay.size), "Int")
    if isinstance(e, AlignOfTypeExpr):
        q = _canonical_type(getattr(e, "query_type", e.type_name))
        lay = _query_layout(ctx, q, e)
        return _Value(ir.Constant(ir.IntType(64), lay.align), "Int")
    if isinstance(e, BitSizeOfTypeExpr):
        bits = getattr(e, "query_bits", None)
        if not isinstance(bits, int):
            q = _canonical_type(getattr(e, "query_type", e.type_name))
            lay = _query_layout(ctx, q, e)
            bits = lay.bits
        return _Value(ir.Constant(ir.IntType(64), bits), "Int")
    if isinstance(e, MaxValTypeExpr):
        info = _int_info(_canonical_type(e.type_name))
        if info is None:
            return _Value(ir.Constant(ir.IntType(64), 0), "Int")
        bits, signed = info
        if signed:
            v = (1 << (bits - 1)) - 1
        else:
            v = (1 << bits) - 1
        return _Value(ir.Constant(ir.IntType(bits), v), _canonical_type(e.type_name))
    if isinstance(e, MinValTypeExpr):
        info = _int_info(_canonical_type(e.type_name))
        if info is None:
            return _Value(ir.Constant(ir.IntType(64), 0), "Int")
        bits, signed = info
        v = -(1 << (bits - 1)) if signed else 0
        return _Value(ir.Constant(ir.IntType(bits), v), _canonical_type(e.type_name))
    if isinstance(e, SizeOfValueExpr):
        q = getattr(e, "query_type", None)
        if not isinstance(q, str):
            q = _expr_type(state, e.expr)
        lay = _query_layout(ctx, q, e)
        return _Value(ir.Constant(ir.IntType(64), lay.size), "Int")
    if isinstance(e, AlignOfValueExpr):
        q = getattr(e, "query_type", None)
        if not isinstance(q, str):
            q = _expr_type(state, e.expr)
        lay = _query_layout(ctx, q, e)
        return _Value(ir.Constant(ir.IntType(64), lay.align), "Int")
    if isinstance(e, IndexExpr):
        elem_ty, _, idx64, ln, data_ptr = _compile_index_base(
            ctx,
            state,
            e.obj,
            e.index,
            overflow_mode,
            e,
        )
        _emit_oob_trap(ctx, state, idx64, ln)
        elem_ptr = b.gep(data_ptr, [idx64])
        return _Value(b.load(elem_ptr), elem_ty)
    if isinstance(e, ArrayLit):
        arr_ty = _canonical_type(_expr_type(state, e))
        elem_ty = _slice_inner_type(arr_ty) if _is_slice_type(arr_ty) else "Any"
        vals: list[ir.Value] = []
        for el in e.elements:
            v = _compile_expr(ctx, state, el, overflow_mode=overflow_mode)
            vals.append(_coerce_value(ctx, state, v.value, v.ty, elem_ty, el))

        i64 = ir.IntType(64)
        i8p = ir.IntType(8).as_pointer()
        header_i8 = _alloc_bytes(ctx, state, ir.Constant(i64, 16), ir.Constant(i64, 8), e, stack_ok=True)
        header_ptr = b.bitcast(header_i8, ctx.slice_header_ty.as_pointer())
        len_ptr = b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
        data_ptr = b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
        b.store(ir.Constant(i64, len(vals)), len_ptr)
        if vals:
            elem_sz, elem_align = _storage_size_align(ctx, elem_ty, e)
            total = elem_sz * len(vals)
            data_i8 = _alloc_bytes(
                ctx,
                state,
                ir.Constant(i64, total),
                ir.Constant(i64, elem_align),
                e,
                stack_ok=True,
            )
            b.store(data_i8, data_ptr)
            elem_ll = _llvm_type(ctx, elem_ty)
            typed = b.bitcast(data_i8, elem_ll.as_pointer())
            for i, vv in enumerate(vals):
                p = b.gep(typed, [ir.Constant(i64, i)])
                b.store(vv, p)
        else:
            b.store(ir.Constant(i8p, None), data_ptr)
        return _Value(header_i8, arr_ty)
    
    # Enhanced syntax expression compilation
    if isinstance(e, MethodCall):
        # Compile object
        obj_val = _compile_expr(ctx, state, e.obj, overflow_mode=overflow_mode)
        
        # For now, treat method calls as regular function calls
        # In a full implementation, this would look up methods on the object type
        args = []
        for arg in e.args:
            arg_val = _compile_expr(ctx, state, arg, overflow_mode=overflow_mode)
            args.append(arg_val)
        
        # Create a regular function call with object as first argument
        all_args = [obj_val] + args
        method_name = f"{_expr_type(state, e.obj)}_{e.method}"
        
        # Try to find the method function
        if method_name in ctx.fn_map:
            fn = ctx.fn_map[method_name]
            arg_values = [_coerce_value(ctx, state, arg.value, arg.ty, param_ty, arg) 
                         for arg, param_ty in zip(all_args, ctx.fn_sigs[method_name].params)]
            call_val = b.call(fn, [arg.value for arg in arg_values])
            return _Value(call_val, ctx.fn_sigs[method_name].ret)
        else:
            # Fallback: return a placeholder
            return _Value(ir.Constant(ir.IntType(64), 0), "Int")
    
    if isinstance(e, VectorLiteral):
        # Create vector literal (simplified as array)
        if not e.elements:
            # Empty vector
            arr_type = ir.ArrayType(ir.IntType(8), 0)
            header_ptr = b.alloca(ctx.slice_header_ty)
            len_val = ir.Constant(ir.IntType(64), 0)
            b.store(len_val, b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]))
            b.store(ir.Constant(ir.IntType(8).as_pointer(), None), b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]))
            return _Value(header_ptr, "Vec<Any>")
        
        # Non-empty vector - compile elements
        element_vals = []
        element_type = None
        for element in e.elements:
            elem_val = _compile_expr(ctx, state, element, overflow_mode=overflow_mode)
            element_vals.append(elem_val)
            if element_type is None:
                element_type = elem_val.ty
        
        # Create array and slice header (simplified)
        arr_type = ir.ArrayType(_llvm_type(ctx, element_type or "Int"), len(element_vals))
        arr_ptr = b.alloca(arr_type)
        
        # Store elements
        for i, elem_val in enumerate(element_vals):
            elem_ptr = b.gep(arr_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
            coerced = _coerce_value(ctx, state, elem_val.value, elem_val.ty, element_type or "Int", element)
            b.store(coerced, elem_ptr)
        
        # Create slice header
        header_ptr = b.alloca(ctx.slice_header_ty)
        len_val = ir.Constant(ir.IntType(64), len(element_vals))
        b.store(len_val, b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)]))
        data_ptr = b.bitcast(arr_ptr, ir.IntType(8).as_pointer())
        b.store(data_ptr, b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)]))
        
        return _Value(header_ptr, f"Vec<{element_type or 'Any'}>")
    
    if isinstance(e, MapLiteral):
        # Create map literal (simplified as struct with fields)
        if not e.pairs:
            # Empty map - return null pointer
            return _Value(ir.Constant(ir.IntType(8).as_pointer(), None), "Map<Any, Any>")
        
        # Non-empty map (simplified - just return a placeholder)
        return _Value(ir.Constant(ir.IntType(8).as_pointer(), None), "Map<Any, Any>")
    
    if isinstance(e, SetLiteral):
        # Create set literal (simplified as array)
        if not e.elements:
            # Empty set
            return _Value(ir.Constant(ir.IntType(8).as_pointer(), None), "Set<Any>")
        
        # Non-empty set (simplified - just return a placeholder)
        return _Value(ir.Constant(ir.IntType(8).as_pointer(), None), "Set<Any>")
    
    if isinstance(e, StructLiteral):
        # Create struct literal with positional arguments
        if e.struct_name not in ctx.struct_decls:
            raise CodegenError(_diag(e, f"undefined struct {e.struct_name}"))
        
        struct_info = ctx.structs[e.struct_name]
        
        # Compile arguments
        arg_values = []
        for i, arg in enumerate(e.args):
            if i < len(struct_info.field_types):
                field_type = struct_info.field_types[i]
                arg_val = _compile_expr(ctx, state, arg, overflow_mode=overflow_mode)
                coerced = _coerce_value(ctx, state, arg_val.value, arg_val.ty, field_type, arg)
                arg_values.append(coerced)
        
        # Allocate struct and store fields
        struct_ptr = b.alloca(struct_info.ty)
        for i, arg_val in enumerate(arg_values):
            field_ptr = b.gep(struct_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), i)])
            b.store(arg_val, field_ptr)
        
        return _Value(struct_ptr, e.struct_name)
    
    if isinstance(e, IfExpression):
        # Compile if expression
        cond_val = _compile_expr(ctx, state, e.cond, overflow_mode=overflow_mode)
        cond_coerced = _coerce_value(ctx, state, cond_val.value, cond_val.ty, "Bool", e.cond)
        
        # Create basic blocks
        then_block = state.fn_ir.append_basic_block("if_then")
        else_block = state.fn_ir.append_basic_block("if_else")
        end_block = state.fn_ir.append_basic_block("if_end")
        
        # Branch based on condition
        b.cbranch(cond_coerced, then_block, else_block)
        
        # Then block
        b.position_at_end(then_block)
        then_val = _compile_expr(ctx, state, e.then_expr, overflow_mode=overflow_mode)
        then_block_terminated = _is_terminated(state)
        if not then_block_terminated:
            b.branch(end_block)
        
        # Else block
        b.position_at_end(else_block)
        else_val = _compile_expr(ctx, state, e.else_expr, overflow_mode=overflow_mode)
        else_block_terminated = _is_terminated(state)
        if not else_block_terminated:
            b.branch(end_block)
        
        # End block
        b.position_at_end(end_block)
        
        # Create phi node
        result_type = then_val.ty
        phi = b.phi(_llvm_type(ctx, result_type))
        phi.add_incoming(then_val.value, then_block)
        phi.add_incoming(else_val.value, else_block)
        
        return _Value(phi, result_type)

    raise CodegenError(_diag(e, f"internal: unexpected expression node {type(e).__name__}"))


def _load_struct_field_value(
    ctx: _ModuleCtx,
    state: _FnState,
    ptr: ir.Value,
    sinfo: _StructInfo,
    field_index: int,
    field_ty: str,
    node: Any,
) -> _Value:
    b = state.builder
    field_name = sinfo.decl.fields[field_index][0]
    if sinfo.packed:
        raw, bits, _ = _packed_load_bits(ctx, state, ptr, sinfo, field_name, node)
        ll = _llvm_type(ctx, field_ty)
        if isinstance(ll, ir.IntType) and bits != ll.width:
            if ll.width > bits:
                info = _int_info(field_ty)
                if info is not None and info[1]:
                    fv = b.sext(raw, ll)
                else:
                    fv = b.zext(raw, ll)
            else:
                fv = b.trunc(raw, ll)
        else:
            fv = raw
        return _Value(fv, field_ty)
    fld = b.gep(ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), field_index)])
    return _Value(b.load(fld), field_ty)


def _compile_match_condition(
    ctx: _ModuleCtx,
    state: _FnState,
    subj: _Value,
    pat: Any,
    overflow_mode: str,
) -> ir.Value:
    b = state.builder
    if isinstance(pat, WildcardPattern):
        return ir.Constant(ir.IntType(1), 1)
    if isinstance(pat, Name):
        return ir.Constant(ir.IntType(1), 1)
    if isinstance(pat, LiteralPattern):
        # Compile literal pattern matching
        if isinstance(pat.value, IntLit):
            pat_val = _compile_expr(ctx, state, pat.value, overflow_mode)
            return b.icmp_signed("==", subj.value, pat_val.value)
        elif isinstance(pat.value, BoolLit):
            pat_val = _compile_expr(ctx, state, pat.value, overflow_mode)
            return b.icmp_signed("==", subj.value, pat_val.value)
        # Add more literal types as needed
        return ir.Constant(ir.IntType(1), 0)
    if isinstance(pat, (RangePattern, RangeExpr)):
        # Compile range pattern matching
        start_val = _compile_expr(ctx, state, pat.start, overflow_mode)
        end_val = _compile_expr(ctx, state, pat.end, overflow_mode)
        info = _int_info(subj.ty)
        signed = True if info is None else info[1]
        cmp = b.icmp_signed if signed else b.icmp_unsigned
        if pat.inclusive:
            ge_start = cmp(">=", subj.value, start_val.value)
            le_end = cmp("<=", subj.value, end_val.value)
            return b.and_(ge_start, le_end)
        else:
            ge_start = cmp(">=", subj.value, start_val.value)
            lt_end = cmp("<", subj.value, end_val.value)
            return b.and_(ge_start, lt_end)
    if isinstance(pat, SlicePattern):
        seq = _sequence_parts_from_value(ctx, state, subj, pat)
        if seq is None:
            return ir.Constant(ir.IntType(1), 0)
        elem_ty, ln, data_i8 = seq
        elem_ptr = b.bitcast(data_i8, _llvm_type(ctx, elem_ty).as_pointer())
        need = ir.Constant(ir.IntType(64), len(pat.patterns))
        if pat.rest_pattern is None:
            len_ok = b.icmp_unsigned("==", ln, need)
        else:
            len_ok = b.icmp_unsigned(">=", ln, need)
        cond = len_ok
        for i, sub in enumerate(pat.patterns):
            ep = b.gep(elem_ptr, [ir.Constant(ir.IntType(64), i)])
            ev = _Value(b.load(ep), elem_ty)
            sub_cond = _compile_match_condition(ctx, state, ev, sub, overflow_mode)
            cond = b.and_(cond, sub_cond)
        return cond
    if isinstance(pat, TuplePattern):
        seq = _sequence_parts_from_value(ctx, state, subj, pat)
        if seq is None:
            return ir.Constant(ir.IntType(1), 0)
        elem_ty, ln, data_i8 = seq
        elem_ptr = b.bitcast(data_i8, _llvm_type(ctx, elem_ty).as_pointer())
        need = ir.Constant(ir.IntType(64), len(pat.patterns))
        cond = b.icmp_unsigned("==", ln, need)
        for i, sub in enumerate(pat.patterns):
            ep = b.gep(elem_ptr, [ir.Constant(ir.IntType(64), i)])
            ev = _Value(b.load(ep), elem_ty)
            sub_cond = _compile_match_condition(ctx, state, ev, sub, overflow_mode)
            cond = b.and_(cond, sub_cond)
        return cond
    if isinstance(pat, StructPattern):
        struct_name = pat.struct_name
        subj_ty = _strip_ref_type(_canonical_type(subj.ty))
        if struct_name not in ctx.structs or subj_ty != struct_name:
            return ir.Constant(ir.IntType(1), 0)
        sinfo = ctx.structs[struct_name]
        ptr = _struct_ptr(ctx, state, subj.value, subj.ty, sinfo, pat)
        cond = ir.Constant(ir.IntType(1), 1)
        for fname, sub in pat.field_patterns.items():
            idx = sinfo.field_index.get(fname)
            if idx is None:
                return ir.Constant(ir.IntType(1), 0)
            fty = sinfo.field_types[idx]
            fv = _load_struct_field_value(ctx, state, ptr, sinfo, idx, fty, pat)
            sub_cond = _compile_match_condition(ctx, state, fv, sub, overflow_mode)
            cond = b.and_(cond, sub_cond)
        return cond
    if isinstance(pat, GuardedPattern):
        cond = _compile_match_condition(ctx, state, subj, pat.pattern, overflow_mode)
        guard_val = _compile_expr(ctx, state, pat.guard, overflow_mode)
        guard_bool = _coerce_value(ctx, state, guard_val.value, guard_val.ty, "Bool", pat.guard)
        return b.and_(cond, guard_bool)
    if isinstance(pat, OrPattern):
        out = ir.Constant(ir.IntType(1), 0)
        for alt in pat.patterns:
            out = b.or_(out, _compile_match_condition(ctx, state, subj, alt, overflow_mode))
        return out
    if isinstance(pat, Call) and isinstance(pat.fn, Name):
        struct_name = pat.fn.value
        subj_ty = _strip_ref_type(_canonical_type(subj.ty))
        if struct_name in ctx.structs and subj_ty == struct_name:
            sinfo = ctx.structs[struct_name]
            if len(pat.args) != len(sinfo.decl.fields):
                return ir.Constant(ir.IntType(1), 0)
            ptr = _struct_ptr(ctx, state, subj.value, subj.ty, sinfo, pat)
            cond = ir.Constant(ir.IntType(1), 1)
            for i, (sub, fty) in enumerate(zip(pat.args, sinfo.field_types)):
                fv = _load_struct_field_value(ctx, state, ptr, sinfo, i, fty, pat)
                sub_cond = _compile_match_condition(ctx, state, fv, sub, overflow_mode)
                cond = b.and_(cond, sub_cond)
            return cond
    pv = _compile_expr(ctx, state, pat, overflow_mode=overflow_mode)
    pvv = _coerce_value(ctx, state, pv.value, pv.ty, subj.ty, pat)
    if isinstance(subj.value.type, (ir.FloatType, ir.DoubleType)):
        return b.fcmp_ordered("==", subj.value, pvv)
    return b.icmp_unsigned("==", subj.value, pvv)


def _compile_match_bindings(
    ctx: _ModuleCtx,
    state: _FnState,
    subj: _Value,
    pat: Any,
) -> None:
    b = state.builder
    if isinstance(pat, Name):
        if pat.value == "_":
            return
        name = pat.value
        ty = _canonical_type(subj.ty)
        ptr = state.vars.get(name)
        if ptr is None:
            ptr = b.alloca(_llvm_type(ctx, ty), name=name)
            state.vars[name] = ptr
            state.var_types[name] = ty
        v = _coerce_value(ctx, state, subj.value, subj.ty, ty, pat)
        b.store(v, ptr)
        return
    if isinstance(pat, WildcardPattern):
        return
    if isinstance(pat, GuardedPattern):
        _compile_match_bindings(ctx, state, subj, pat.pattern)
        return
    if isinstance(pat, (RangePattern, RangeExpr, LiteralPattern)):
        return
    if isinstance(pat, SlicePattern):
        seq = _sequence_parts_from_value(ctx, state, subj, pat)
        if seq is None:
            return
        elem_ty, _, data_i8 = seq
        elem_ptr = b.bitcast(data_i8, _llvm_type(ctx, elem_ty).as_pointer())
        for i, sub in enumerate(pat.patterns):
            ep = b.gep(elem_ptr, [ir.Constant(ir.IntType(64), i)])
            ev = _Value(b.load(ep), elem_ty)
            _compile_match_bindings(ctx, state, ev, sub)
        return
    if isinstance(pat, TuplePattern):
        seq = _sequence_parts_from_value(ctx, state, subj, pat)
        if seq is None:
            return
        elem_ty, _, data_i8 = seq
        elem_ptr = b.bitcast(data_i8, _llvm_type(ctx, elem_ty).as_pointer())
        for i, sub in enumerate(pat.patterns):
            ep = b.gep(elem_ptr, [ir.Constant(ir.IntType(64), i)])
            ev = _Value(b.load(ep), elem_ty)
            _compile_match_bindings(ctx, state, ev, sub)
        return
    if isinstance(pat, OrPattern):
        # Binding extraction for `|` alternatives is not lowered here because
        # the matched alternative is not tracked in this stage.
        return
    if isinstance(pat, Call) and isinstance(pat.fn, Name):
        struct_name = pat.fn.value
        subj_ty = _strip_ref_type(_canonical_type(subj.ty))
        if struct_name in ctx.structs and subj_ty == struct_name:
            sinfo = ctx.structs[struct_name]
            if len(pat.args) != len(sinfo.decl.fields):
                return
            ptr = _struct_ptr(ctx, state, subj.value, subj.ty, sinfo, pat)
            for i, (sub, fty) in enumerate(zip(pat.args, sinfo.field_types)):
                fv = _load_struct_field_value(ctx, state, ptr, sinfo, i, fty, pat)
                _compile_match_bindings(ctx, state, fv, sub)
        return
    if isinstance(pat, StructPattern):
        struct_name = pat.struct_name
        subj_ty = _strip_ref_type(_canonical_type(subj.ty))
        if struct_name in ctx.structs and subj_ty == struct_name:
            sinfo = ctx.structs[struct_name]
            ptr = _struct_ptr(ctx, state, subj.value, subj.ty, sinfo, pat)
            for fname, sub in pat.field_patterns.items():
                idx = sinfo.field_index.get(fname)
                if idx is None:
                    return
                fty = sinfo.field_types[idx]
                fv = _load_struct_field_value(ctx, state, ptr, sinfo, idx, fty, pat)
                _compile_match_bindings(ctx, state, fv, sub)
        return


def _pattern_int_literal_value(pat: Any) -> int | None:
    if isinstance(pat, LiteralPattern):
        val = pat.value
        if isinstance(val, IntLit):
            return int(val.value)
        if isinstance(val, Literal) and isinstance(val.value, int) and not isinstance(val.value, bool):
            return int(val.value)
        return None
    if isinstance(pat, Literal) and isinstance(pat.value, int) and not isinstance(pat.value, bool):
        return int(pat.value)
    if isinstance(pat, Unary) and pat.op == "-":
        inner = _pattern_int_literal_value(pat.expr)
        if inner is not None:
            return -inner
    if isinstance(pat, CastExpr):
        return _pattern_int_literal_value(pat.expr)
    return None


def _compile_match_arm_body(ctx: _ModuleCtx, state: _FnState, body: Any, overflow_mode: str) -> None:
    if isinstance(body, list):
        for sub in body:
            _compile_stmt(ctx, state, sub, overflow_mode)
            if _is_terminated(state):
                break
        return
    _compile_expr(ctx, state, body, overflow_mode=overflow_mode)


def _try_compile_int_switch_match(
    ctx: _ModuleCtx,
    state: _FnState,
    st: MatchStmt,
    subj: _Value,
    end_block: ir.Block,
    overflow_mode: str,
) -> bool:
    b = state.builder
    subj_ll = subj.value.type
    if not isinstance(subj_ll, ir.IntType):
        return False
    if _int_info(subj.ty) is None:
        return False

    case_arms: list[tuple[int, Any, Any]] = []
    default_arm: tuple[Any, Any] | None = None
    seen_values: set[int] = set()
    for pat, body in st.arms:
        if isinstance(pat, (GuardedPattern, OrPattern)):
            return False
        if isinstance(pat, WildcardPattern) or isinstance(pat, Name):
            if default_arm is None:
                default_arm = (pat, body)
            continue
        pv = _pattern_int_literal_value(pat)
        if pv is None:
            return False
        if pv in seen_values:
            continue
        seen_values.add(pv)
        case_arms.append((pv, pat, body))

    if not case_arms:
        return False

    default_block = state.fn_ir.append_basic_block("match_default")
    switch_inst = b.switch(subj.value, default_block)
    ll_bits = subj_ll.width
    mask = (1 << ll_bits) - 1
    signed = bool(_int_info(subj.ty)[1])

    arm_blocks: list[tuple[Any, Any, ir.Block]] = []
    for idx, (pv, pat, body) in enumerate(case_arms):
        raw = pv if signed else (pv & mask)
        case_const = ir.Constant(subj_ll, raw)
        arm_block = state.fn_ir.append_basic_block(f"match_switch_arm_{idx}")
        switch_inst.add_case(case_const, arm_block)
        arm_blocks.append((pat, body, arm_block))

    for pat, body, arm_block in arm_blocks:
        state.builder.position_at_end(arm_block)
        _compile_match_bindings(ctx, state, subj, pat)
        _compile_match_arm_body(ctx, state, body, overflow_mode)
        if not _is_terminated(state):
            state.builder.branch(end_block)

    state.builder.position_at_end(default_block)
    if default_arm is not None:
        dpat, dbody = default_arm
        _compile_match_bindings(ctx, state, subj, dpat)
        _compile_match_arm_body(ctx, state, dbody, overflow_mode)
    if not _is_terminated(state):
        state.builder.branch(end_block)
    return True


def _compile_stmt(ctx: _ModuleCtx, state: _FnState, st: Any, overflow_mode: str) -> None:
    b = state.builder

    if isinstance(st, LetStmt):
        if st.reassign_if_exists and st.name in state.vars:
            _compile_stmt(
                ctx,
                state,
                AssignStmt(
                    target=Name(st.name, st.pos, st.line, st.col),
                    op="=",
                    expr=st.expr,
                    pos=st.pos,
                    line=st.line,
                    col=st.col,
                    explicit_set=False,
                ),
                overflow_mode,
            )
            return
        ty = _canonical_type(st.type_name or _expr_type(state, st.expr))
        promote_allocs = st.name in state.stack_promotion_bindings
        if promote_allocs:
            state.stack_alloc_depth += 1
        try:
            val = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
        finally:
            if promote_allocs:
                state.stack_alloc_depth -= 1
        v = _coerce_value(ctx, state, val.value, val.ty, ty, st)
        ptr = b.alloca(_llvm_type(ctx, ty), name=st.name)
        b.store(v, ptr)
        state.vars[st.name] = ptr
        state.var_types[st.name] = ty
        return

    if isinstance(st, AssignStmt):
        if isinstance(st.target, Name):
            name = st.target.value
            if name not in state.vars:
                raise CodegenError(_diag(st, f"undefined local {name}"))
            ty = state.var_types.get(name, "Int")
            ptr = state.vars[name]
            rhs = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
            if st.op == "=":
                v = _coerce_value(ctx, state, rhs.value, rhs.ty, ty, st)
                b.store(v, ptr)
                return
            lhs = _Value(b.load(ptr), ty)
            lv = lhs
            rv = _Value(_coerce_value(ctx, state, rhs.value, rhs.ty, ty, st), ty)
            if _is_text_type(ty):
                if st.op != "+=":
                    raise CodegenError(_diag(st, f"internal: unexpected assignment op {st.op} for text type"))
                fn = _declare_runtime(ctx, "astra_str_concat")
                lsp = _coerce_value(ctx, state, lv.value, lv.ty, "String", st.target)
                rsp = _coerce_value(ctx, state, rv.value, rv.ty, "String", st.expr)
                out = b.call(fn, [lsp, rsp])
                b.store(out, ptr)
                return
            if _is_float_type(ty):
                if st.op == "+=":
                    out = b.fadd(lv.value, rv.value)
                elif st.op == "-=":
                    out = b.fsub(lv.value, rv.value)
                elif st.op == "*=":
                    out = b.fmul(lv.value, rv.value)
                elif st.op == "/=":
                    out = b.fdiv(lv.value, rv.value)
                elif st.op == "%=":
                    out = b.frem(lv.value, rv.value)
                else:
                    raise CodegenError(_diag(st, f"internal: unexpected assignment op {st.op}"))
                b.store(out, ptr)
                return
            info = _int_info(ty)
            signed = True if info is None else info[1]
            if st.op == "+=":
                out = b.add(lv.value, rv.value)
            elif st.op == "-=":
                out = b.sub(lv.value, rv.value)
            elif st.op == "*=":
                out = b.mul(lv.value, rv.value)
            elif st.op == "/=":
                out = _lower_checked_divrem(ctx, state, lv.value, rv.value, signed=signed, is_div=True)
            elif st.op == "%=":
                out = _lower_checked_divrem(ctx, state, lv.value, rv.value, signed=signed, is_div=False)
            elif st.op == "&=":
                out = b.and_(lv.value, rv.value)
            elif st.op == "|=":
                out = b.or_(lv.value, rv.value)
            elif st.op == "^=":
                out = b.xor(lv.value, rv.value)
            elif st.op == "<<=":
                out = _lower_checked_shift(ctx, state, lv.value, rv.value, signed=signed, left_shift=True)
            elif st.op == ">>=":
                out = _lower_checked_shift(ctx, state, lv.value, rv.value, signed=signed, left_shift=False)
            else:
                raise CodegenError(_diag(st, f"internal: unexpected assignment op {st.op}"))
            b.store(out, ptr)
            return

        if isinstance(st.target, FieldExpr):
            obj = _compile_expr(ctx, state, st.target.obj, overflow_mode=overflow_mode)
            obj_ty = _expr_type(state, st.target.obj)
            base_ty = obj_ty[5:] if obj_ty.startswith("&mut ") else (obj_ty[1:] if obj_ty.startswith("&") else obj_ty)
            sinfo = ctx.structs.get(base_ty)
            if sinfo is None:
                raise CodegenError(_diag(st, f"field assignment requires struct receiver, got {obj_ty}"))
            idx = sinfo.field_index.get(st.target.field)
            if idx is None:
                raise CodegenError(_diag(st, f"unknown field {st.target.field} on {base_ty}"))
            ptr = _struct_ptr(ctx, state, obj.value, obj_ty, sinfo, st)
            fty = sinfo.field_types[idx]
            rhs = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
            rv = _coerce_value(ctx, state, rhs.value, rhs.ty, fty, st)
            if sinfo.packed:
                if st.op == "=":
                    out = rv
                else:
                    lv_raw, bits, _ = _packed_load_bits(ctx, state, ptr, sinfo, st.target.field, st)
                    lv = b.trunc(lv_raw, _llvm_type(ctx, fty))
                    if _is_float_type(fty):
                        if st.op == "+=":
                            out = b.fadd(lv, rv)
                        elif st.op == "-=":
                            out = b.fsub(lv, rv)
                        elif st.op == "*=":
                            out = b.fmul(lv, rv)
                        elif st.op == "/=":
                            out = b.fdiv(lv, rv)
                        elif st.op == "%=":
                            out = b.frem(lv, rv)
                        else:
                            raise CodegenError(_diag(st, f"internal: unexpected field assignment op {st.op}"))
                    else:
                        info = _int_info(fty)
                        signed = True if info is None else info[1]
                        if st.op == "+=":
                            out = b.add(lv, rv)
                        elif st.op == "-=":
                            out = b.sub(lv, rv)
                        elif st.op == "*=":
                            out = b.mul(lv, rv)
                        elif st.op == "/=":
                            out = _lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=True)
                        elif st.op == "%=":
                            out = _lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=False)
                        elif st.op == "&=":
                            out = b.and_(lv, rv)
                        elif st.op == "|=":
                            out = b.or_(lv, rv)
                        elif st.op == "^=":
                            out = b.xor(lv, rv)
                        elif st.op == "<<=":
                            out = _lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=True)
                        elif st.op == ">>=":
                            out = _lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=False)
                        else:
                            raise CodegenError(_diag(st, f"internal: unexpected field assignment op {st.op}"))
                    if isinstance(out.type, ir.IntType) and out.type.width != bits:
                        if out.type.width > bits:
                            out = b.trunc(out, ir.IntType(bits))
                        elif _is_signed_int(fty):
                            out = b.sext(out, ir.IntType(bits))
                        else:
                            out = b.zext(out, ir.IntType(bits))
                _packed_store_bits(ctx, state, ptr, sinfo, st.target.field, out, st)
                return

            fld = b.gep(ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), idx)])
            if st.op == "=":
                b.store(rv, fld)
                return
            lv = b.load(fld)
            if _is_text_type(fty):
                if st.op != "+=":
                    raise CodegenError(_diag(st, f"internal: unexpected field assignment op {st.op} for text type"))
                fn = _declare_runtime(ctx, "astra_str_concat")
                lsp = _coerce_value(ctx, state, lv, fty, "String", st.target)
                rsp = _coerce_value(ctx, state, rv, fty, "String", st.expr)
                out = b.call(fn, [lsp, rsp])
                b.store(out, fld)
                return
            if _is_float_type(fty):
                if st.op == "+=":
                    out = b.fadd(lv, rv)
                elif st.op == "-=":
                    out = b.fsub(lv, rv)
                elif st.op == "*=":
                    out = b.fmul(lv, rv)
                elif st.op == "/=":
                    out = b.fdiv(lv, rv)
                elif st.op == "%=":
                    out = b.frem(lv, rv)
                else:
                    raise CodegenError(_diag(st, f"internal: unexpected field assignment op {st.op}"))
            else:
                info = _int_info(fty)
                signed = True if info is None else info[1]
                if st.op == "+=":
                    out = b.add(lv, rv)
                elif st.op == "-=":
                    out = b.sub(lv, rv)
                elif st.op == "*=":
                    out = b.mul(lv, rv)
                elif st.op == "/=":
                    out = _lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=True)
                elif st.op == "%=":
                    out = _lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=False)
                elif st.op == "&=":
                    out = b.and_(lv, rv)
                elif st.op == "|=":
                    out = b.or_(lv, rv)
                elif st.op == "^=":
                    out = b.xor(lv, rv)
                elif st.op == "<<=":
                    out = _lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=True)
                elif st.op == ">>=":
                    out = _lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=False)
                else:
                    raise CodegenError(_diag(st, f"internal: unexpected field assignment op {st.op}"))
            b.store(out, fld)
            return

        if isinstance(st.target, IndexExpr):
            elem_ty, _, idx64, ln, data_ptr = _compile_index_base(
                ctx,
                state,
                st.target.obj,
                st.target.index,
                overflow_mode,
                st,
            )
            _emit_oob_trap(ctx, state, idx64, ln)
            elem_ptr = b.gep(data_ptr, [idx64])
            rhs = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
            rv = _coerce_value(ctx, state, rhs.value, rhs.ty, elem_ty, st)
            if st.op == "=":
                b.store(rv, elem_ptr)
                return
            lv = b.load(elem_ptr)
            if _is_text_type(elem_ty):
                if st.op != "+=":
                    raise CodegenError(_diag(st, f"internal: unexpected index assignment op {st.op} for text type"))
                fn = _declare_runtime(ctx, "astra_str_concat")
                lsp = _coerce_value(ctx, state, lv, elem_ty, "String", st.target)
                rsp = _coerce_value(ctx, state, rv, elem_ty, "String", st.expr)
                out = b.call(fn, [lsp, rsp])
                b.store(out, elem_ptr)
                return
            if _is_float_type(elem_ty):
                if st.op == "+=":
                    out = b.fadd(lv, rv)
                elif st.op == "-=":
                    out = b.fsub(lv, rv)
                elif st.op == "*=":
                    out = b.fmul(lv, rv)
                elif st.op == "/=":
                    out = b.fdiv(lv, rv)
                elif st.op == "%=":
                    out = b.frem(lv, rv)
                else:
                    raise CodegenError(_diag(st, f"internal: unexpected index assignment op {st.op}"))
            else:
                info = _int_info(elem_ty)
                signed = True if info is None else info[1]
                if st.op == "+=":
                    out = b.add(lv, rv)
                elif st.op == "-=":
                    out = b.sub(lv, rv)
                elif st.op == "*=":
                    out = b.mul(lv, rv)
                elif st.op == "/=":
                    out = _lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=True)
                elif st.op == "%=":
                    out = _lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=False)
                elif st.op == "&=":
                    out = b.and_(lv, rv)
                elif st.op == "|=":
                    out = b.or_(lv, rv)
                elif st.op == "^=":
                    out = b.xor(lv, rv)
                elif st.op == "<<=":
                    out = _lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=True)
                elif st.op == ">>=":
                    out = _lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=False)
                else:
                    raise CodegenError(_diag(st, f"internal: unexpected index assignment op {st.op}"))
            b.store(out, elem_ptr)
            return

        if isinstance(st.target, Unary) and st.target.op == "*":
            ptr_src = _compile_expr(ctx, state, st.target.expr, overflow_mode=overflow_mode)
            tgt_ty = _expr_type(state, st.target)
            ll_tgt = _llvm_type(ctx, tgt_ty)
            base_ptr = ptr_src.value
            if isinstance(base_ptr.type, ir.IntType):
                base_ptr = b.inttoptr(base_ptr, ll_tgt.as_pointer())
            elif isinstance(base_ptr.type, ir.PointerType):
                if base_ptr.type != ll_tgt.as_pointer():
                    base_ptr = b.bitcast(base_ptr, ll_tgt.as_pointer())
            else:
                raise CodegenError(_diag(st, f"cannot assign through non-pointer type {ptr_src.ty}"))
            rhs = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
            rv = _coerce_value(ctx, state, rhs.value, rhs.ty, tgt_ty, st)
            if st.op == "=":
                b.store(rv, base_ptr)
                return
            lv = b.load(base_ptr)
            if _is_float_type(tgt_ty):
                if st.op == "+=":
                    out = b.fadd(lv, rv)
                elif st.op == "-=":
                    out = b.fsub(lv, rv)
                elif st.op == "*=":
                    out = b.fmul(lv, rv)
                elif st.op == "/=":
                    out = b.fdiv(lv, rv)
                elif st.op == "%=":
                    out = b.frem(lv, rv)
                else:
                    raise CodegenError(_diag(st, f"internal: unexpected deref assignment op {st.op}"))
            else:
                info = _int_info(tgt_ty)
                signed = True if info is None else info[1]
                if st.op == "+=":
                    out = b.add(lv, rv)
                elif st.op == "-=":
                    out = b.sub(lv, rv)
                elif st.op == "*=":
                    out = b.mul(lv, rv)
                elif st.op == "/=":
                    out = _lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=True)
                elif st.op == "%=":
                    out = _lower_checked_divrem(ctx, state, lv, rv, signed=signed, is_div=False)
                elif st.op == "&=":
                    out = b.and_(lv, rv)
                elif st.op == "|=":
                    out = b.or_(lv, rv)
                elif st.op == "^=":
                    out = b.xor(lv, rv)
                elif st.op == "<<=":
                    out = _lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=True)
                elif st.op == ">>=":
                    out = _lower_checked_shift(ctx, state, lv, rv, signed=signed, left_shift=False)
                else:
                    raise CodegenError(_diag(st, f"internal: unexpected deref assignment op {st.op}"))
            b.store(out, base_ptr)
            return

        raise CodegenError(_diag(st, "internal: unexpected assignment target"))

    if isinstance(st, ReturnStmt):
        if state.ret_alloca is not None:
            if st.expr is None:
                rv = _default_value(ctx, state.ret_type)
                b.store(rv, state.ret_alloca)
            else:
                v = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
                cv = _coerce_value(ctx, state, v.value, v.ty, state.ret_type, st)
                b.store(cv, state.ret_alloca)
        if not _is_terminated(state):
            b.branch(state.epilogue_block)
        return

    if isinstance(st, ExprStmt):
        _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
        return

    if isinstance(st, BreakStmt):
        if not state.loop_stack:
            raise CodegenError(_diag(st, "break outside loop"))
        _, end_block = state.loop_stack[-1]
        b.branch(end_block)
        return

    if isinstance(st, ContinueStmt):
        if not state.loop_stack:
            raise CodegenError(_diag(st, "continue outside loop"))
        cont_block, _ = state.loop_stack[-1]
        b.branch(cont_block)
        return

    if isinstance(st, IfStmt):
        cond = _compile_expr(ctx, state, st.cond, overflow_mode=overflow_mode)
        c = _coerce_value(ctx, state, cond.value, cond.ty, "Bool", st.cond)
        fn = state.fn_ir
        then_block = fn.append_basic_block("if_then")
        else_block = fn.append_basic_block("if_else")
        end_block = fn.append_basic_block("if_end")
        b.cbranch(c, then_block, else_block)

        b.position_at_end(then_block)
        for sub in st.then_body:
            _compile_stmt(ctx, state, sub, overflow_mode)
            if _is_terminated(state):
                break
        if not _is_terminated(state):
            b.branch(end_block)

        b.position_at_end(else_block)
        for sub in st.else_body:
            _compile_stmt(ctx, state, sub, overflow_mode)
            if _is_terminated(state):
                break
        if not _is_terminated(state):
            b.branch(end_block)

        b.position_at_end(end_block)
        return

    if isinstance(st, WhileStmt):
        fn = state.fn_ir
        cond_block = fn.append_basic_block("while_cond")
        body_block = fn.append_basic_block("while_body")
        end_block = fn.append_basic_block("while_end")
        b.branch(cond_block)

        b.position_at_end(cond_block)
        cond = _compile_expr(ctx, state, st.cond, overflow_mode=overflow_mode)
        c = _coerce_value(ctx, state, cond.value, cond.ty, "Bool", st.cond)
        b.cbranch(c, body_block, end_block)

        b.position_at_end(body_block)
        state.loop_stack.append((cond_block, end_block))
        for sub in st.body:
            _compile_stmt(ctx, state, sub, overflow_mode)
            if _is_terminated(state):
                break
        state.loop_stack.pop()
        if not _is_terminated(state):
            b.branch(cond_block)

        b.position_at_end(end_block)
        return

    if isinstance(st, ForStmt):
        raise CodegenError(_diag(st, "internal: unlowered for-in loop"))

    if isinstance(st, MatchStmt):
        fn = state.fn_ir
        end_block = fn.append_basic_block("match_end")
        subj = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
        if _try_compile_int_switch_match(ctx, state, st, subj, end_block, overflow_mode):
            state.builder.position_at_end(end_block)
            return
        cur_check = state.builder.block
        for i, (pat, body) in enumerate(st.arms):
            state.builder.position_at_end(cur_check)
            arm_block = fn.append_basic_block(f"match_arm_{i}")
            next_block = fn.append_basic_block(f"match_next_{i}")
            cmpv = _compile_match_condition(ctx, state, subj, pat, overflow_mode)
            state.builder.cbranch(cmpv, arm_block, next_block)

            state.builder.position_at_end(arm_block)
            _compile_match_bindings(ctx, state, subj, pat)
            _compile_match_arm_body(ctx, state, body, overflow_mode)
            
            if not _is_terminated(state):
                state.builder.branch(end_block)
            cur_check = next_block

        state.builder.position_at_end(cur_check)
        if not _is_terminated(state):
            state.builder.branch(end_block)
        state.builder.position_at_end(end_block)
        return

    if isinstance(st, ComptimeStmt):
        return

    if isinstance(st, UnsafeStmt):
        # Compile unsafe block with tracking
        _compile_unsafe_block(ctx, state, st, overflow_mode)
        return


def _compile_unsafe_block(ctx: _ModuleCtx, state: _FnState, st: UnsafeStmt, overflow_mode: str):
    """Compile an unsafe block with proper tracking."""
    # Create a marker for unsafe operations
    b = state.builder
    
    # Add debug info for unsafe block (if debug info is available)
    unsafe_comment = b.comment("begin unsafe block")
    
    # Compile all statements in the unsafe block
    for sub in st.body:
        _compile_stmt(ctx, state, sub, overflow_mode)
        if _is_terminated(state):
            break
    
    # Add end marker
    end_comment = b.comment("end unsafe block")


def _is_unsafe_operation(expr: Any) -> bool:
    """Check if an expression represents an unsafe operation."""
    if isinstance(expr, Call):
        # Check for unsafe function calls
        if hasattr(expr.fn, 'value') and expr.fn.value.startswith("unsafe_"):
            return True
        # Check for raw pointer operations
        if hasattr(expr.fn, 'value') and expr.fn.value in ["transmute", "ptr_cast", "raw_ptr"]:
            return True
    elif isinstance(expr, Cast):
        # Check for unsafe casts
        src_ty = _canonical_type(expr.expr.ty if hasattr(expr.expr, 'ty') else "Any")
        dst_ty = expr.type_name
        if _is_unsafe_cast(src_ty, dst_ty):
            return True
    return False


def _is_unsafe_cast(src_ty: str, dst_ty: str) -> bool:
    """Check if a cast is unsafe."""
    # Pointer to integer casts
    if src_ty.startswith("*") and _is_int_type(dst_ty):
        return True
    # Integer to pointer casts
    if _is_int_type(src_ty) and dst_ty.startswith("*"):
        return True
    # Function pointer to non-function pointer
    if src_ty.startswith("fn(") and dst_ty.startswith("*") and not dst_ty.startswith("fn("):
        return True
    # Between unrelated pointer types
    if src_ty.startswith("*") and dst_ty.startswith("*") and src_ty != dst_ty:
        return True
    return False


def _compile_iterator_for_loop(ctx, state, st, iterable_val, cond_block, body_block, end_block, overflow_mode):
        end_block = fn.append_basic_block("iter_end")
        
        # Compile the iterable expression
        iterable_val = _compile_expr(ctx, state, st.iterable, overflow_mode=overflow_mode)
        
        # Handle different iterable types
        if isinstance(st.iterable, RangeExpr):
            # Range iteration: for item in start..end
            _compile_range_for_loop(ctx, state, st, iterable_val, cond_block, body_block, end_block, overflow_mode)
        elif hasattr(st.iterable, 'type') and 'Vec' in str(st.iterable.type):
            # Vec iteration: for item in vec
            _compile_vec_for_loop(ctx, state, st, iterable_val, cond_block, body_block, end_block, overflow_mode)
        elif hasattr(st.iterable, 'type') and 'str' in str(st.iterable.type):
            # String iteration: for ch in string
            _compile_string_for_loop(ctx, state, st, iterable_val, cond_block, body_block, end_block, overflow_mode)
        else:
            # Fallback: treat as generic iterable with index-based iteration
            _compile_generic_for_loop(ctx, state, st, iterable_val, cond_block, body_block, end_block, overflow_mode)
        
        return


def _compile_range_for_loop(ctx, state, st, range_val, cond_block, body_block, end_block, overflow_mode):
    """Compile a for loop over a range expression."""
    b = state.builder
    
    # Extract start and end from range
    start_val = range_val.start if hasattr(range_val, 'start') else ir.Constant(ir.IntType(64), 0)
    end_val = range_val.end if hasattr(range_val, 'end') else range_val
    
    # Create loop counter
    counter_ptr = b.alloca(_llvm_type(ctx, "Int"), name=f"{st.var_name}_counter")
    b.store(start_val, counter_ptr)
    
    b.branch(cond_block)
    
    # Condition block
    b.position_at_end(cond_block)
    counter = b.load(counter_ptr)
    if hasattr(range_val, 'inclusive') and range_val.inclusive:
        cond = b.icmp_signed("<=", counter, end_val)
    else:
        cond = b.icmp_signed("<", counter, end_val)
    b.cbranch(cond, body_block, end_block)
    
    # Body block
    b.position_at_end(body_block)
    var_ptr = b.alloca(_llvm_type(ctx, "Int"), name=st.var_name)
    b.store(counter, var_ptr)
    state.vars[st.var_name] = var_ptr
    state.var_types[st.var_name] = "Int"
    
    # Compile body statements
    state.loop_stack.append((cond_block, end_block))
    for sub in st.body:
        _compile_stmt(ctx, state, sub, overflow_mode)
        if _is_terminated(state):
            break
    state.loop_stack.pop()
    
    if not _is_terminated(state):
        # Increment counter
        new_counter = b.add(counter, ir.Constant(ir.IntType(64), 1))
        b.store(new_counter, counter_ptr)
        b.branch(cond_block)
    
    # End block
    b.position_at_end(end_block)


def _compile_vec_for_loop(ctx, state, st, vec_val, cond_block, body_block, end_block, overflow_mode):
    """Compile a for loop over a Vec."""
    b = state.builder
    
    # Get pointer to Vec data and length
    # This is a simplified implementation - real Vec would have specific structure
    data_ptr = b.extract_value(vec_val, 0) if hasattr(vec_val, 'operands') else vec_val
    length = b.extract_value(vec_val, 1) if hasattr(vec_val, 'operands') and len(vec_val.operands) > 1 else ir.Constant(ir.IntType(64), 10)
    
    # Create loop counter
    counter_ptr = b.alloca(_llvm_type(ctx, "Int"), name=f"{st.var_name}_index")
    b.store(ir.Constant(ir.IntType(64), 0), counter_ptr)
    
    b.branch(cond_block)
    
    # Condition block
    b.position_at_end(cond_block)
    index = b.load(counter_ptr)
    cond = b.icmp_signed("<", index, length)
    b.cbranch(cond, body_block, end_block)
    
    # Body block
    b.position_at_end(body_block)
    # Get element at index: element = data[index]
    element_ptr = b.gep(data_ptr, [index])
    element = b.load(element_ptr)
    
    var_ptr = b.alloca(_llvm_type(ctx, "Int"), name=st.var_name)
    b.store(element, var_ptr)
    state.vars[st.var_name] = var_ptr
    state.var_types[st.var_name] = "Int"
    
    # Compile body statements
    state.loop_stack.append((cond_block, end_block))
    for sub in st.body:
        _compile_stmt(ctx, state, sub, overflow_mode)
        if _is_terminated(state):
            break
    state.loop_stack.pop()
    
    if not _is_terminated(state):
        # Increment counter
        new_index = b.add(index, ir.Constant(ir.IntType(64), 1))
        b.store(new_index, counter_ptr)
        b.branch(cond_block)
    
    # End block
    b.position_at_end(end_block)


def _compile_string_for_loop(ctx, state, st, str_val, cond_block, body_block, end_block, overflow_mode):
    """Compile a for loop over a string."""
    b = state.builder
    
    # Get string pointer and length
    # Simplified implementation
    str_ptr = str_val if hasattr(str_val, 'type') and 'ptr' in str_val.type else b.gep(str_val, [ir.Constant(ir.IntType(64), 0)])
    length = b.extract_value(str_val, 1) if hasattr(str_val, 'operands') and len(str_val.operands) > 1 else ir.Constant(ir.IntType(64), 10)
    
    # Create loop counter
    counter_ptr = b.alloca(_llvm_type(ctx, "Int"), name=f"{st.var_name}_index")
    b.store(ir.Constant(ir.IntType(64), 0), counter_ptr)
    
    b.branch(cond_block)
    
    # Condition block
    b.position_at_end(cond_block)
    index = b.load(counter_ptr)
    cond = b.icmp_signed("<", index, length)
    b.cbranch(cond, body_block, end_block)
    
    # Body block
    b.position_at_end(body_block)
    # Get character at index: char = str_ptr[index]
    char_ptr = b.gep(str_ptr, [index])
    char = b.load(char_ptr)
    
    var_ptr = b.alloca(_llvm_type(ctx, "char"), name=st.var_name)
    b.store(char, var_ptr)
    state.vars[st.var_name] = var_ptr
    state.var_types[st.var_name] = "char"
    
    # Compile body statements
    state.loop_stack.append((cond_block, end_block))
    for sub in st.body:
        _compile_stmt(ctx, state, sub, overflow_mode)
        if _is_terminated(state):
            break
    state.loop_stack.pop()
    
    if not _is_terminated(state):
        # Increment counter
        new_index = b.add(index, ir.Constant(ir.IntType(64), 1))
        b.store(new_index, counter_ptr)
        b.branch(cond_block)
    
    # End block
    b.position_at_end(end_block)


def _compile_generic_for_loop(ctx, state, st, iterable_val, cond_block, body_block, end_block, overflow_mode):
    """Fallback compilation for generic iterables using index-based iteration."""
    b = state.builder
    
    # Create loop counter (index)
    counter_ptr = b.alloca(_llvm_type(ctx, "Int"), name=f"{st.var_name}_index")
    b.store(ir.Constant(ir.IntType(64), 0), counter_ptr)
    
    # Assume a fixed length for generic iterables (simplified)
    length = ir.Constant(ir.IntType(64), 10)
    
    b.branch(cond_block)
    
    # Condition block
    b.position_at_end(cond_block)
    index = b.load(counter_ptr)
    cond = b.icmp_signed("<", index, length)
    b.cbranch(cond, body_block, end_block)
    
    # Body block
    b.position_at_end(body_block)
    # Get element using index (simplified)
    element = index  # Just use the index as the element value
    
    var_ptr = b.alloca(_llvm_type(ctx, "Int"), name=st.var_name)
    b.store(element, var_ptr)
    state.vars[st.var_name] = var_ptr
    state.var_types[st.var_name] = "Int"
    
    # Compile body statements
    state.loop_stack.append((cond_block, end_block))
    for sub in st.body:
        _compile_stmt(ctx, state, sub, overflow_mode)
        if _is_terminated(state):
            break
    state.loop_stack.pop()
    
    if not _is_terminated(state):
        # Increment counter
        new_index = b.add(index, ir.Constant(ir.IntType(64), 1))
        b.store(new_index, counter_ptr)
        b.branch(cond_block)
    
    # End block
    b.position_at_end(end_block)
    
    raise CodegenError(_diag(st, f"internal: unexpected statement node {type(st).__name__}"))


def _build_structs(ctx: _ModuleCtx, prog: Program) -> None:
    # First pass: placeholders
    for item in prog.items:
        if isinstance(item, StructDecl):
            ctx.struct_decls[item.name] = item
            ctx.structs[item.name] = _StructInfo(decl=item, ty=ir.LiteralStructType([]), field_index={}, field_types=[])

    for item in prog.items:
        if not isinstance(item, StructDecl):
            continue
        field_types = [_canonical_type(t) for _, t in item.fields]
        sinfo = ctx.structs[item.name]
        if item.packed:
            try:
                lay = layout_of_struct(item.name, ctx.struct_decls, mode="query", _cache=ctx.layout_cache)
            except LayoutError as err:
                raise CodegenError(_diag(item, str(err))) from err
            storage_size = max(1, lay.size)
            sinfo.ty = ir.ArrayType(ir.IntType(8), storage_size)
            sinfo.storage_size = lay.size
            sinfo.field_bit_offsets = lay.field_bit_offsets.copy()
            sinfo.field_bits = lay.field_bits.copy()
            sinfo.packed = True
        else:
            ll_fields = [_llvm_type(ctx, t) for t in field_types]
            sinfo.ty = ir.LiteralStructType(ll_fields, packed=False)
            sinfo.packed = False
            try:
                lay = layout_of_struct(item.name, ctx.struct_decls, mode="query", _cache=ctx.layout_cache)
                sinfo.storage_size = lay.size
            except LayoutError:
                sinfo.storage_size = 0
        sinfo.field_types = field_types
        sinfo.field_index = {fname: i for i, (fname, _) in enumerate(item.fields)}


def _inline_attr_for_fn(item: FnDecl) -> str | None:
    # Conservative size-based hinting; LLVM can ignore if inapplicable.
    if bool(getattr(item, "extern", False)):
        return None
    if item.name in {"main", "_start"}:
        return None
    body = list(getattr(item, "body", []) or [])
    if not body:
        return None

    cost = 0
    for st in body:
        if isinstance(st, (ReturnStmt, ExprStmt, LetStmt, AssignStmt)):
            cost += 1
            continue
        # Control-flow-heavy bodies should not be force-inlined.
        return None
    if cost <= 2:
        return "alwaysinline"
    if cost <= 5:
        return "inlinehint"
    return None


def _declare_functions(ctx: _ModuleCtx, prog: Program, freestanding: bool) -> tuple[list[FnDecl], str | None]:
    user_fns: list[FnDecl] = []
    user_main_key: str | None = None

    for item in prog.items:
        if isinstance(item, ExternFnDecl):
            key = item.name
            sig = ctx.fn_sigs[key]
            fnty = ir.FunctionType(_llvm_type(ctx, sig.ret), [_llvm_type(ctx, t) for t in sig.params], var_arg=sig.variadic)
            ir_fn = ir.Function(ctx.module, fnty, name=key)
            _apply_abi_attributes_to_extern_fn(ctx, item, sig, ir_fn)
            ctx.fn_map[key] = ir_fn
            for lib in sig.link_libs:
                if lib:
                    ctx.ffi_libs.add(lib)
        elif isinstance(item, FnDecl):
            key = item.symbol or item.name
            sig = ctx.fn_sigs[key]
            llvm_name = key
            if not freestanding and item.name == "main":
                llvm_name = "__astra_user_main"
                user_main_key = key
            fnty = ir.FunctionType(_llvm_type(ctx, sig.ret), [_llvm_type(ctx, t) for t in sig.params])
            fn_ir = ir.Function(ctx.module, fnty, name=llvm_name)
            fn_ir.attributes.add("nounwind")
            inline_attr = _inline_attr_for_fn(item)
            if inline_attr is not None:
                fn_ir.attributes.add(inline_attr)
            ctx.fn_map[key] = fn_ir
            user_fns.append(item)

    return user_fns, user_main_key


def _compile_function(ctx: _ModuleCtx, item: FnDecl, overflow_mode: str) -> None:
    key = item.symbol or item.name
    sig = ctx.fn_sigs[key]
    fn_ir = ctx.fn_map[key]
    entry = fn_ir.append_basic_block("entry")
    epilogue = fn_ir.append_basic_block("epilogue")
    b = ir.IRBuilder(entry)

    ret_ty = _canonical_type(sig.ret)
    ret_alloca: ir.Value | None = None
    if ret_ty not in {"Void", "Never"}:
        ret_alloca = b.alloca(_llvm_type(ctx, ret_ty), name="ret")
        b.store(_default_value(ctx, ret_ty), ret_alloca)

    state = _FnState(
        fn_name=key,
        fn_ir=fn_ir,
        builder=b,
        ret_type=ret_ty,
        ret_alloca=ret_alloca,
        epilogue_block=epilogue,
        vars={},
        var_types={},
    )

    body_stmts: list[Any] = list(item.body)
    state.stack_promotion_bindings = _compute_stack_promotion_bindings(ctx, body_stmts)

    for (pname, pty), arg in zip(item.params, fn_ir.args):
        ptype = _canonical_type(pty)
        ptr = b.alloca(_llvm_type(ctx, ptype), name=pname)
        b.store(arg, ptr)
        state.vars[pname] = ptr
        state.var_types[pname] = ptype

    for st in body_stmts:
        _compile_stmt(ctx, state, st, overflow_mode)
        if _is_terminated(state):
            break

    if not _is_terminated(state):
        b.branch(epilogue)

    b.position_at_end(epilogue)
    if ret_ty in {"Void", "Never"}:
        if not _is_terminated(state):
            b.ret_void()
    else:
        if not _is_terminated(state):
            b.ret(b.load(ret_alloca))


def _emit_hosted_main_wrapper(ctx: _ModuleCtx, user_main_key: str | None) -> None:
    if user_main_key is None:
        return
    if "main" in ctx.fn_map and isinstance(ctx.fn_map["main"], ir.Function):
        # User explicitly declared symbol main externally; wrapper name conflict avoided by renaming user main.
        pass
    fnty = ir.FunctionType(ir.IntType(32), [])
    wrapper = ir.Function(ctx.module, fnty, name="main")
    wrapper.attributes.add("nounwind")
    b = ir.IRBuilder(wrapper.append_basic_block("entry"))

    target = ctx.fn_map[user_main_key]
    sig = ctx.fn_sigs[user_main_key]
    out = b.call(target, [])
    ret_ty = _canonical_type(sig.ret)
    if ret_ty in {"Void", "Never"}:
        b.ret(ir.Constant(ir.IntType(32), 0))
        return
    if _is_float_type(ret_ty):
        sat = _declare_fptoi_sat_intrinsic(ctx, bits=32, signed=True, from_ty=out.type)
        outv = b.call(sat, [out])
    elif isinstance(out.type, ir.IntType):
        if out.type.width > 32:
            outv = b.trunc(out, ir.IntType(32))
        elif out.type.width < 32:
            outv = b.sext(out, ir.IntType(32))
        else:
            outv = out
    elif isinstance(out.type, ir.PointerType):
        outv = b.ptrtoint(out, ir.IntType(32))
    else:
        outv = ir.Constant(ir.IntType(32), 0)
    b.ret(outv)


def to_llvm_ir(
    prog: Program,
    freestanding: bool = False,
    overflow_mode: str = "trap",
    triple: str | None = None,
    profile: str = "debug",
    filename: str = "<input>",
) -> str:
    """Lower an analyzed AST program into LLVM IR text.
    
    Parameters:
        prog: Program AST to read or mutate.
        freestanding: Whether hosted-runtime features are disallowed.
        overflow_mode: Integer overflow behavior mode requested by the caller.
        triple: Input value used by this routine.
        profile: Build profile selector, typically `debug` or `release`.
    
    Returns:
        Value described by the function return annotation.
    """
    _init_llvm_once()

    # Ensure semantic annotations (symbols/inferred types) are present for direct backend use.
    if (
        not getattr(prog, "_analyzed", False)
        or getattr(prog, "_analyzed_freestanding", None) != freestanding
    ):
        analyze(prog, filename=filename, freestanding=freestanding)
    lower_for_loops(prog)

    module = ir.Module(name="astra_module")
    module.triple = triple or binding.get_default_triple()

    try:
        try:
            target = binding.Target.from_triple(module.triple)
        except Exception:
            target = binding.Target.from_default_triple()
        target_machine = target.create_target_machine(opt=3 if profile == "release" else 0)
        module.data_layout = target_machine.target_data
    except Exception:
        pass

    ctx = _ModuleCtx(
        module=module,
        triple=module.triple,
        freestanding=freestanding,
        structs={},
        struct_decls={},
        slice_header_ty=ir.LiteralStructType([ir.IntType(64), ir.IntType(8).as_pointer()]),
        fn_sigs=_collect_fn_sigs(prog),
        fn_map={},
        string_globals={},
        ffi_libs=set(getattr(prog, "ffi_libs", set())),
        layout_cache={},
        monomorph_aliases={},
    )
    
    # Store program reference for Any runtime checking
    ctx.prog = prog

    _build_structs(ctx, prog)
    user_fns, user_main_key = _declare_functions(ctx, prog, freestanding=freestanding)

    mono_instances = getattr(prog, "monomorph_instances", {})
    if isinstance(mono_instances, dict):
        for key, mono_symbol in mono_instances.items():
            if not isinstance(mono_symbol, str) or not mono_symbol:
                continue
            if not isinstance(key, tuple) or not key:
                continue
            base_symbol = key[0]
            if not isinstance(base_symbol, str):
                continue
            if mono_symbol in ctx.fn_sigs:
                continue
            base_sig = ctx.fn_sigs.get(base_symbol)
            if base_sig is None:
                continue
            ctx.monomorph_aliases[mono_symbol] = base_symbol
            # Reuse the existing lowered implementation via alias lookup.
            ctx.fn_sigs[mono_symbol] = base_sig

    for fn in user_fns:
        _compile_function(ctx, fn, overflow_mode)

    if not freestanding:
        _emit_hosted_main_wrapper(ctx, user_main_key)

    mod = binding.parse_assembly(str(module))
    mod.verify()

    out = str(mod)
    return out if out.endswith("\n") else out + "\n"
