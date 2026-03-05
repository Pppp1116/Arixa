from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astra.ast import *
from astra.codegen import CodegenError
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
    defer_sites: list[DeferStmt] = field(default_factory=list)
    defer_counts: dict[int, ir.Value] = field(default_factory=dict)


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
    cpu_dispatch: bool = False
    cpu_target: str = "baseline"
    multiversion_variants: dict[str, list[str]] = field(default_factory=dict)


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
    return t.endswith("?") or (t.startswith("Option<") and t.endswith(">"))


def _option_inner_type(typ: str) -> str:
    t = typ.strip()
    if t.endswith("?"):
        return t[:-1].strip()
    if t.startswith("Option<") and t.endswith(">"):
        return t[7:-1].strip()
    return typ


def _int_info(typ: str) -> tuple[int, bool] | None:
    c = _canonical_type(typ)
    if c in {"Int", "isize"}:
        return 64, True
    if c == "usize":
        return 64, False
    return parse_int_type_name(c)


def _is_float_type(typ: str) -> bool:
    return _canonical_type(typ) in {"Float", "f32", "f64"}


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


def _parse_fn_type(typ: str) -> tuple[list[str], str] | None:
    text = _canonical_type(typ)
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
    if close + 4 > len(text) or text[close + 1 : close + 5] != " -> ":
        return None
    params_text = text[3:close].strip()
    ret = text[close + 5 :].strip()
    params = [] if not params_text else _split_top_level(params_text, ",")
    return params, ret


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
        return layout_of_type(c, ctx.struct_decls, mode="query")
    except LayoutError as err:
        raise CodegenError(_diag(node, str(err))) from err


def _storage_size_align(ctx: _ModuleCtx, typ: str, node: Any) -> tuple[int, int]:
    c = _canonical_type(typ)
    try:
        lay = layout_of_type(c, ctx.struct_decls, mode="query")
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
    mask_v = (1 << bits) - 1
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

    mask_v = (1 << bits) - 1
    field_mask = mask_v << bit_shift
    window_bits = nbytes * 8
    full_mask = (1 << window_bits) - 1
    clear_mask = full_mask ^ field_mask
    inserted = b.shl(b.and_(nb, ir.Constant(int_ty, mask_v)), ir.Constant(int_ty, bit_shift))
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
            out[name] = _FnSig(name=name, params=[_canonical_type(typ) for _, typ in item.params], ret=_canonical_type(item.ret), extern=False)
        elif isinstance(item, ExternFnDecl):
            out[item.name] = _FnSig(name=item.name, params=[_canonical_type(typ) for _, typ in item.params], ret=_canonical_type(item.ret), extern=True)
    return out


def _llvm_type(ctx: _ModuleCtx, typ: str) -> ir.Type:
    c = _canonical_type(typ)
    if _is_option_type(c):
        return ir.IntType(8).as_pointer()
    if c == "Bool":
        return ir.IntType(1)
    info = _int_info(c)
    if info is not None:
        bits, _ = info
        return ir.IntType(bits)
    if c == "f32":
        return ir.FloatType()
    if c in {"Float", "f64"}:
        return ir.DoubleType()
    if c in {"Void", "Never"}:
        return ir.VoidType()
    if c in ctx.structs:
        return ctx.structs[c].ty.as_pointer()
    if c.startswith("&mut "):
        return _llvm_type(ctx, c[5:]).as_pointer()
    if c.startswith("&"):
        return _llvm_type(ctx, c[1:]).as_pointer()
    if c.startswith("fn("):
        return ir.IntType(8).as_pointer()
    if c in {"String", "str"} or _is_vec_type(c) or _is_slice_type(c):
        return ir.IntType(8).as_pointer()
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


def _is_terminated(state: _FnState) -> bool:
    return state.builder.block.terminator is not None


def _is_signed_int(typ: str) -> bool:
    info = _int_info(typ)
    return bool(info[1]) if info is not None else True


def _coerce_value(ctx: _ModuleCtx, state: _FnState, v: ir.Value, from_ty: str, to_ty: str, node: Any) -> ir.Value:
    from_c = _canonical_type(from_ty)
    to_c = _canonical_type(to_ty)
    if from_c == to_c:
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
        mem = _alloc_bytes(ctx, state, ir.Constant(i64, sz), ir.Constant(i64, al), node)
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
            if name in {"print", "__print", "free", "panic", "__free", "__panic"}:
                return "Void"
            if name in {"alloc", "__alloc"}:
                return "usize"
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


def _declare_runtime(ctx: _ModuleCtx, name: str) -> ir.Function:
    if name in ctx.fn_map:
        fn = ctx.fn_map[name]
        if isinstance(fn, ir.Function):
            return fn
    i64 = ir.IntType(64)
    i128 = ir.IntType(128)
    i8p = ir.IntType(8).as_pointer()
    i1 = ir.IntType(1)
    if name == "astra_print_i64":
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
    elif name == "astra_spawn_store":
        fnty = ir.FunctionType(i64, [i64])
    elif name == "astra_join":
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
    elif name == "astra_secure_bytes":
        fnty = ir.FunctionType(i8p, [i64])
    elif name == "astra_utf8_encode":
        fnty = ir.FunctionType(i8p, [i8p])
    elif name == "astra_utf8_decode":
        fnty = ir.FunctionType(i8p, [i8p])
    elif name == "astra_alloc":
        fnty = ir.FunctionType(i64, [i64, i64])
    elif name == "astra_free":
        fnty = ir.FunctionType(ir.VoidType(), [i64, i64, i64])
    elif name == "astra_panic":
        fnty = ir.FunctionType(ir.VoidType(), [i8p, i64])
    elif name == "astra_fmod":
        fnty = ir.FunctionType(ir.DoubleType(), [ir.DoubleType(), ir.DoubleType()])
    elif name.startswith("astra_i128_"):
        fnty = ir.FunctionType(i128, [i128, i128])
    elif name.startswith("astra_u128_"):
        fnty = ir.FunctionType(i128, [i128, i128])
    else:
        raise CodegenError(f"internal: unknown runtime symbol {name}")
    fn = ir.Function(ctx.module, fnty, name=name)
    ctx.fn_map[name] = fn
    return fn


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


def _alloc_bytes(ctx: _ModuleCtx, state: _FnState, size_i64: ir.Value, align_i64: ir.Value, node: Any) -> ir.Value:
    b = state.builder
    i64 = ir.IntType(64)
    i8p = ir.IntType(8).as_pointer()
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
    obj = _compile_expr(ctx, state, obj_expr, overflow_mode=overflow_mode)
    obj_ty = _expr_type(state, obj_expr)
    base_ty = _strip_ref_type(obj_ty)
    if _is_vec_type(base_ty):
        elem_ty = _vec_inner_type(base_ty)
    elif _is_slice_type(base_ty):
        elem_ty = _slice_inner_type(base_ty)
    else:
        raise CodegenError(_diag(node, f"index/get expects Vec<T> or [T], got {obj_ty}"))

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
    zero = ir.Constant(rv.type, 0)
    lim = ir.Constant(rv.type, bits)
    if signed:
        nonneg = b.icmp_signed(">=", rv, zero)
        lt = b.icmp_signed("<", rv, lim)
        ok = b.and_(nonneg, lt)
    else:
        ok = b.icmp_unsigned("<", rv, lim)
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

    if base == "vec_new":
        if len(call.args) != 0:
            raise CodegenError(_diag(call, "vec_new expects 0 arguments"))
        header_i8 = _alloc_bytes(ctx, state, ir.Constant(i64, 16), ir.Constant(i64, 8), call)
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
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "print expects 1 argument"))
        arg_node = call.args[0]
        if isinstance(arg_node, Literal) and isinstance(arg_node.value, str):
            g = _get_string_global(ctx, arg_node.value)
            ptr = b.gep(g, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
            fn = _declare_runtime(ctx, "astra_print_str")
            b.call(fn, [ptr, ir.Constant(i64, len(arg_node.value.encode("utf-8")))])
        else:
            arg = _compile_expr(ctx, state, arg_node)
            aty = _canonical_type(arg.ty)
            if aty in {"String", "str"}:
                sp = _as_string_ptr(arg, arg_node)
                len_fn = _declare_runtime(ctx, "astra_len_str")
                ln = b.call(len_fn, [sp])
                fn = _declare_runtime(ctx, "astra_print_str")
                b.call(fn, [sp, ln])
            else:
                v = _as_i64(arg, call)
                fn = _declare_runtime(ctx, "astra_print_i64")
                b.call(fn, [v])
        return _Value(ir.Constant(i64, 0), "Void")

    if base == "alloc":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "alloc expects 1 argument"))
        sz = _compile_expr(ctx, state, call.args[0])
        sv = _coerce_value(ctx, state, sz.value, sz.ty, "usize", call)
        fn = _declare_runtime(ctx, "astra_alloc")
        out = b.call(fn, [sv, ir.Constant(i64, 8)])
        return _Value(out, "usize")

    if base == "free":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "free expects 1 argument"))
        p = _compile_expr(ctx, state, call.args[0])
        pv = _coerce_value(ctx, state, p.value, p.ty, "usize", call)
        fn = _declare_runtime(ctx, "astra_free")
        b.call(fn, [pv, ir.Constant(i64, 0), ir.Constant(i64, 8)])
        return _Value(ir.Constant(i64, 0), "Void")

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
        pseudo = Call(fn=call.args[0], args=call.args[1:], pos=call.pos, line=call.line, col=call.col)
        resolved = getattr(call, "spawn_resolved_name", None)
        if isinstance(resolved, str):
            pseudo.resolved_name = resolved
        out = _compile_call(ctx, state, pseudo, overflow_mode=overflow_mode)
        fn = _declare_runtime(ctx, "astra_spawn_store")
        tid = b.call(fn, [_as_any_i64(out, call)])
        return _Value(tid, "Int")

    if base == "join":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "join expects 1 argument"))
        t = _compile_expr(ctx, state, call.args[0])
        fn = _declare_runtime(ctx, "astra_join")
        out = b.call(fn, [_as_i64(t, call.args[0])])
        return _Value(out, "Any")

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

    if base == "secure_bytes":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "secure_bytes expects 1 argument"))
        n = _compile_expr(ctx, state, call.args[0], overflow_mode=overflow_mode)
        fn = _declare_runtime(ctx, "astra_secure_bytes")
        out = b.call(fn, [_as_i64(n, call.args[0])])
        return _Value(out, "Bytes")

    if base == "utf8_encode":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "utf8_encode expects 1 argument"))
        src = _compile_expr(ctx, state, call.args[0], overflow_mode=overflow_mode)
        fn = _declare_runtime(ctx, "astra_utf8_encode")
        out = b.call(fn, [_as_string_ptr(src, call.args[0])])
        return _Value(out, "Bytes")

    if base == "utf8_decode":
        if len(call.args) != 1:
            raise CodegenError(_diag(call, "utf8_decode expects 1 argument"))
        src = _compile_expr(ctx, state, call.args[0], overflow_mode=overflow_mode)
        fn = _declare_runtime(ctx, "astra_utf8_decode")
        out = b.call(fn, [_as_i8_ptr(state, src.value, call.args[0])])
        return _Value(out, "Option<String>")

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
    if isinstance(call.fn, FieldExpr) and call.fn.field == "get":
        recv_ty = _strip_ref_type(_expr_type(state, call.fn.obj))
        if _is_vec_type(recv_ty) or _is_slice_type(recv_ty):
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
        resolved = call.resolved_name or name
        if name in ctx.structs:
            sinfo = ctx.structs[name]
            if len(call.args) != len(sinfo.field_types):
                raise CodegenError(_diag(call, f"struct {name} expects {len(sinfo.field_types)} args, got {len(call.args)}"))
            fields = {fname: arg for (fname, _), arg in zip(sinfo.decl.fields, call.args)}
            return _compile_struct_init(ctx, state, name, fields, call, overflow_mode)

        if resolved in {
            "print",
            "len",
            "read_file",
            "write_file",
            "args",
            "arg",
            "alloc",
            "free",
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
            "proc_exit",
            "env_get",
            "cwd",
            "proc_run",
            "now_unix",
            "monotonic_ms",
            "sleep_ms",
            "secure_bytes",
            "utf8_encode",
            "utf8_decode",
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
            "__print",
            "__len",
            "__read_file",
            "__write_file",
            "__args",
            "__arg",
            "__alloc",
            "__free",
            "__spawn",
            "__join",
            "__await_result",
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
            "__proc_exit",
            "__env_get",
            "__cwd",
            "__proc_run",
            "__now_unix",
            "__monotonic_ms",
            "__sleep_ms",
            "__secure_bytes",
            "__utf8_encode",
            "__utf8_decode",
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
        if isinstance(callee, ir.Function) and sig is not None:
            args: list[ir.Value] = []
            for arg_node, pty in zip(call.args, sig.params):
                a = _compile_expr(ctx, state, arg_node)
                args.append(_coerce_value(ctx, state, a.value, a.ty, pty, arg_node))
            if len(call.args) != len(sig.params):
                raise CodegenError(_diag(call, f"{resolved} expects {len(sig.params)} args, got {len(call.args)}"))
            out = state.builder.call(callee, args)
            ret = _canonical_type(sig.ret)
            if ret in {"Void", "Never"}:
                return _Value(ir.Constant(ir.IntType(64), 0), ret)
            return _Value(out, ret)

    # Fallback indirect call support for function pointers of known fn(...) type.
    fn_val = _compile_expr(ctx, state, call.fn)
    parsed = _parse_fn_type(fn_val.ty)
    if parsed is None:
        raise CodegenError(_diag(call, f"cannot resolve call target for {type(call.fn).__name__}"))
    param_tys, ret_ty = parsed
    if len(param_tys) != len(call.args):
        raise CodegenError(_diag(call, f"callee expects {len(param_tys)} args, got {len(call.args)}"))
    fnty = ir.FunctionType(_llvm_type(ctx, ret_ty), [_llvm_type(ctx, t) for t in param_tys])
    callee_ptr = fn_val.value
    if isinstance(callee_ptr.type, ir.PointerType) and callee_ptr.type.pointee != fnty:
        callee_ptr = state.builder.bitcast(callee_ptr, fnty.as_pointer())
    args: list[ir.Value] = []
    for arg_node, pty in zip(call.args, param_tys):
        a = _compile_expr(ctx, state, arg_node)
        args.append(_coerce_value(ctx, state, a.value, a.ty, pty, arg_node))
    out = state.builder.call(callee_ptr, args)
    if _canonical_type(ret_ty) in {"Void", "Never"}:
        return _Value(ir.Constant(ir.IntType(64), 0), _canonical_type(ret_ty))
    return _Value(out, _canonical_type(ret_ty))


def _compile_expr(ctx: _ModuleCtx, state: _FnState, e: Any, overflow_mode: str = "trap") -> _Value:
    b = state.builder
    if isinstance(e, WildcardPattern):
        raise CodegenError(_diag(e, "wildcard pattern `_` is only valid in match arms"))
    if isinstance(e, (BindPattern, VariantPattern, GuardPattern)):
        raise CodegenError(_diag(e, "pattern is only valid in match arms"))
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
        if e.value in state.vars:
            ptr = state.vars[e.value]
            ty = state.var_types.get(e.value, "Int")
            return _Value(b.load(ptr), ty)
        sig = ctx.fn_sigs.get(e.value)
        fn = ctx.fn_map.get(e.value)
        if sig is not None and isinstance(fn, ir.Function):
            parsed = f"fn({', '.join(sig.params)}) -> {sig.ret}"
            return _Value(b.bitcast(fn, ir.IntType(8).as_pointer()), parsed)
        raise CodegenError(_diag(e, f"undefined local or function value {e.value}"))
    if isinstance(e, AwaitExpr):
        return _compile_expr(ctx, state, e.expr, overflow_mode=overflow_mode)
    if isinstance(e, CastExpr):
        dst_ty = _canonical_type(e.type_name)
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
                cv = _coerce_value(ctx, state, src.value, src.ty, dst_ty, e)
                return _Value(cv, dst_ty)
        src = _compile_expr(ctx, state, e.expr, overflow_mode=overflow_mode)
        cv = _coerce_value(ctx, state, src.value, src.ty, dst_ty, e)
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
            return _Value(b.add(lv, rv), lty)
        if e.op == "-":
            return _Value(b.sub(lv, rv), lty)
        if e.op == "*":
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
        header_i8 = _alloc_bytes(ctx, state, ir.Constant(i64, 16), ir.Constant(i64, 8), e)
        header_ptr = b.bitcast(header_i8, ctx.slice_header_ty.as_pointer())
        len_ptr = b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 0)])
        data_ptr = b.gep(header_ptr, [ir.Constant(ir.IntType(32), 0), ir.Constant(ir.IntType(32), 1)])
        b.store(ir.Constant(i64, len(vals)), len_ptr)
        if vals:
            elem_sz, elem_align = _storage_size_align(ctx, elem_ty, e)
            total = elem_sz * len(vals)
            data_i8 = _alloc_bytes(ctx, state, ir.Constant(i64, total), ir.Constant(i64, elem_align), e)
            b.store(data_i8, data_ptr)
            elem_ll = _llvm_type(ctx, elem_ty)
            typed = b.bitcast(data_i8, elem_ll.as_pointer())
            for i, vv in enumerate(vals):
                p = b.gep(typed, [ir.Constant(i64, i)])
                b.store(vv, p)
        else:
            b.store(ir.Constant(i8p, None), data_ptr)
        return _Value(header_i8, arr_ty)
    raise CodegenError(_diag(e, f"internal: unexpected expression node {type(e).__name__}"))


def _collect_defer_sites(stmts: list[Any], out: list[DeferStmt]) -> None:
    for st in stmts:
        if isinstance(st, DeferStmt):
            out.append(st)
        elif isinstance(st, IfStmt):
            _collect_defer_sites(st.then_body, out)
            _collect_defer_sites(st.else_body, out)
        elif isinstance(st, WhileStmt):
            _collect_defer_sites(st.body, out)
        elif isinstance(st, ForStmt):
            if isinstance(st.init, LetStmt):
                _collect_defer_sites([st.init], out)
            elif isinstance(st.init, AssignStmt):
                _collect_defer_sites([st.init], out)
            if isinstance(st.step, AssignStmt):
                _collect_defer_sites([st.step], out)
            _collect_defer_sites(st.body, out)
        elif isinstance(st, MatchStmt):
            for _, arm in st.arms:
                _collect_defer_sites(arm, out)
        elif isinstance(st, ComptimeStmt):
            _collect_defer_sites(st.body, out)
        elif isinstance(st, UnsafeStmt):
            _collect_defer_sites(st.body, out)


def _compile_stmt(ctx: _ModuleCtx, state: _FnState, st: Any, overflow_mode: str) -> None:
    b = state.builder

    if isinstance(st, LetStmt):
        ty = _canonical_type(st.type_name or _expr_type(state, st.expr))
        val = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
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

    if isinstance(st, DropStmt):
        if getattr(st, "drop_free", False) and isinstance(st.expr, Name):
            v = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
            pv = _coerce_value(ctx, state, v.value, v.ty, "usize", st.expr)
            fn = _declare_runtime(ctx, "astra_free")
            b.call(fn, [pv, ir.Constant(ir.IntType(64), 0), ir.Constant(ir.IntType(64), 8)])
            return
        _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
        return

    if isinstance(st, DeferStmt):
        cnt_ptr = state.defer_counts.get(id(st))
        if cnt_ptr is None:
            return
        cur = b.load(cnt_ptr)
        b.store(b.add(cur, ir.Constant(ir.IntType(64), 1)), cnt_ptr)
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
        if st.init is not None:
            if isinstance(st.init, LetStmt):
                _compile_stmt(ctx, state, st.init, overflow_mode)
            elif isinstance(st.init, AssignStmt):
                _compile_stmt(ctx, state, st.init, overflow_mode)
            else:
                _compile_expr(ctx, state, st.init, overflow_mode=overflow_mode)

        fn = state.fn_ir
        cond_block = fn.append_basic_block("for_cond")
        body_block = fn.append_basic_block("for_body")
        step_block = fn.append_basic_block("for_step")
        end_block = fn.append_basic_block("for_end")
        b.branch(cond_block)

        b.position_at_end(cond_block)
        if st.cond is None:
            c = ir.Constant(ir.IntType(1), 1)
        else:
            cond = _compile_expr(ctx, state, st.cond, overflow_mode=overflow_mode)
            c = _coerce_value(ctx, state, cond.value, cond.ty, "Bool", st.cond)
        b.cbranch(c, body_block, end_block)

        b.position_at_end(body_block)
        state.loop_stack.append((step_block, end_block))
        for sub in st.body:
            _compile_stmt(ctx, state, sub, overflow_mode)
            if _is_terminated(state):
                break
        state.loop_stack.pop()
        if not _is_terminated(state):
            b.branch(step_block)

        b.position_at_end(step_block)
        if st.step is not None:
            if isinstance(st.step, AssignStmt):
                _compile_stmt(ctx, state, st.step, overflow_mode)
            else:
                _compile_expr(ctx, state, st.step, overflow_mode=overflow_mode)
        if not _is_terminated(state):
            b.branch(cond_block)

        b.position_at_end(end_block)
        return

    if isinstance(st, MatchStmt):
        fn = state.fn_ir
        end_block = fn.append_basic_block("match_end")
        subj = _compile_expr(ctx, state, st.expr, overflow_mode=overflow_mode)
        cur_check = state.builder.block
        for i, (pat, body) in enumerate(st.arms):
            state.builder.position_at_end(cur_check)
            arm_block = fn.append_basic_block(f"match_arm_{i}")
            raw_pat = pat.pattern if isinstance(pat, GuardPattern) else pat
            guard = pat.cond if isinstance(pat, GuardPattern) else None
            if isinstance(raw_pat, VariantPattern):
                raise CodegenError(_diag(raw_pat, "enum variant match patterns are currently only supported on Python backend"))
            if isinstance(raw_pat, (WildcardPattern, BindPattern)):
                if guard is None:
                    state.builder.branch(arm_block)
                else:
                    next_block = fn.append_basic_block(f"match_next_{i}")
                    gv = _compile_expr(ctx, state, guard, overflow_mode=overflow_mode)
                    gb = _coerce_value(ctx, state, gv.value, gv.ty, "Bool", guard)
                    state.builder.cbranch(gb, arm_block, next_block)
            else:
                next_block = fn.append_basic_block(f"match_next_{i}")
                pv = _compile_expr(ctx, state, raw_pat, overflow_mode=overflow_mode)
                pvv = _coerce_value(ctx, state, pv.value, pv.ty, subj.ty, raw_pat)
                if isinstance(subj.value.type, (ir.FloatType, ir.DoubleType)):
                    cmpv = state.builder.fcmp_ordered("==", subj.value, pvv)
                else:
                    cmpv = state.builder.icmp_unsigned("==", subj.value, pvv)
                if guard is not None:
                    gv = _compile_expr(ctx, state, guard, overflow_mode=overflow_mode)
                    gb = _coerce_value(ctx, state, gv.value, gv.ty, "Bool", guard)
                    cmpv = state.builder.and_(cmpv, gb)
                state.builder.cbranch(cmpv, arm_block, next_block)

            state.builder.position_at_end(arm_block)
            for sub in body:
                _compile_stmt(ctx, state, sub, overflow_mode)
                if _is_terminated(state):
                    break
            if not _is_terminated(state):
                state.builder.branch(end_block)
            if isinstance(raw_pat, (WildcardPattern, BindPattern)):
                cur_check = None
                break
            cur_check = next_block

        if cur_check is not None:
            state.builder.position_at_end(cur_check)
            if not _is_terminated(state):
                state.builder.branch(end_block)
        state.builder.position_at_end(end_block)
        return

    if isinstance(st, ComptimeStmt):
        return

    if isinstance(st, UnsafeStmt):
        for sub in st.body:
            _compile_stmt(ctx, state, sub, overflow_mode)
            if _is_terminated(state):
                break
        return

    raise CodegenError(_diag(st, f"internal: unexpected statement node {type(st).__name__}"))


def _emit_defer_epilogue(ctx: _ModuleCtx, state: _FnState, overflow_mode: str) -> None:
    b = state.builder
    fn = state.fn_ir
    for i, site in enumerate(reversed(state.defer_sites)):
        cnt_ptr = state.defer_counts[id(site)]
        cond_block = fn.append_basic_block(f"defer_cond_{i}")
        body_block = fn.append_basic_block(f"defer_body_{i}")
        end_block = fn.append_basic_block(f"defer_end_{i}")
        if not _is_terminated(state):
            b.branch(cond_block)
        b.position_at_end(cond_block)
        c = b.load(cnt_ptr)
        ok = b.icmp_signed(">", c, ir.Constant(ir.IntType(64), 0))
        b.cbranch(ok, body_block, end_block)

        b.position_at_end(body_block)
        cur = b.load(cnt_ptr)
        b.store(b.sub(cur, ir.Constant(ir.IntType(64), 1)), cnt_ptr)
        _compile_expr(ctx, state, site.expr, overflow_mode=overflow_mode)
        if not _is_terminated(state):
            b.branch(cond_block)

        b.position_at_end(end_block)


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
                lay = layout_of_struct(item.name, ctx.struct_decls, mode="query")
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
                lay = layout_of_struct(item.name, ctx.struct_decls, mode="query")
                sinfo.storage_size = lay.size
            except LayoutError:
                sinfo.storage_size = 0
        sinfo.field_types = field_types
        sinfo.field_index = {fname: i for i, (fname, _) in enumerate(item.fields)}




def _has_loop(stmts: list[Any]) -> bool:
    for st in stmts:
        if isinstance(st, (ForStmt, WhileStmt)):
            return True
        if isinstance(st, IfStmt):
            if _has_loop(st.then_body) or _has_loop(st.else_body):
                return True
        if isinstance(st, MatchStmt):
            for _, arm_body in st.arms:
                if _has_loop(arm_body):
                    return True
        if hasattr(st, "body") and isinstance(st.body, list):
            if _has_loop(st.body):
                return True
    return False


def _is_multiversion_candidate(item: FnDecl) -> bool:
    if item.name in {"main", "_start"}:
        return False
    return _has_loop(item.body)


def _variant_suffixes(cpu_target: str) -> list[str]:
    if cpu_target == "baseline":
        return ["baseline"]
    if cpu_target == "avx2":
        return ["baseline", "sse4", "avx2"]
    if cpu_target == "avx512":
        return ["baseline", "sse4", "avx2", "avx512"]
    raise ValueError(f"unsupported cpu target '{cpu_target}', expected one of: baseline, avx2, avx512")


def _variant_features(suffix: str) -> str | None:
    return {
        "baseline": None,
        "sse4": "+sse4.2",
        "avx2": "+avx2",
        "avx512": "+avx512f",
    }.get(suffix)


def _set_variant_attrs(fn: ir.Function, suffix: str) -> None:
    feat = _variant_features(suffix)
    if feat is None:
        return
    # llvmlite does not expose generic key/value target-feature attributes here;
    # keep this as a no-op marker hook to avoid changing optimization semantics.
    _ = fn


def _declare_cpu_probe(ctx: _ModuleCtx, name: str) -> ir.Function:
    f = ctx.fn_map.get(name)
    if isinstance(f, ir.Function):
        return f
    f = ir.Function(ctx.module, ir.FunctionType(ir.IntType(32), []), name=name)
    ctx.fn_map[name] = f
    return f


def _compile_multiversion_dispatcher(ctx: _ModuleCtx, item: FnDecl) -> None:
    key = item.symbol or item.name
    fn_ir = ctx.fn_map[key]
    sig = ctx.fn_sigs[key]
    entry = fn_ir.append_basic_block("entry")
    b = ir.IRBuilder(entry)
    args = list(fn_ir.args)
    variants = ctx.multiversion_variants.get(key, [])
    ordered = [v for v in ["avx512", "avx2", "sse4", "baseline"] if v in variants]

    for idx, variant in enumerate(ordered):
        if variant == "baseline":
            target = ctx.fn_map[f"{key}__mv_baseline"]
            out = b.call(target, args)
            if _canonical_type(sig.ret) in {"Void", "Never"}:
                b.ret_void()
            else:
                b.ret(out)
            return
        probe = _declare_cpu_probe(ctx, f"astra_cpu_has_{variant}")
        probe_val = b.call(probe, [])
        cond = b.icmp_unsigned("!=", probe_val, ir.Constant(ir.IntType(32), 0))
        then_bb = fn_ir.append_basic_block(f"mv_{variant}")
        else_bb = fn_ir.append_basic_block(f"mv_next_{idx}")
        b.cbranch(cond, then_bb, else_bb)
        b.position_at_end(then_bb)
        target = ctx.fn_map[f"{key}__mv_{variant}"]
        out = b.call(target, args)
        if _canonical_type(sig.ret) in {"Void", "Never"}:
            b.ret_void()
        else:
            b.ret(out)
        b.position_at_end(else_bb)
    # Fallback
    target = ctx.fn_map[f"{key}__mv_baseline"]
    out = b.call(target, args)
    if _canonical_type(sig.ret) in {"Void", "Never"}:
        b.ret_void()
    else:
        b.ret(out)

def _declare_functions(ctx: _ModuleCtx, prog: Program, freestanding: bool) -> tuple[list[FnDecl], str | None]:
    user_fns: list[FnDecl] = []
    user_main_key: str | None = None

    for item in prog.items:
        if isinstance(item, ExternFnDecl):
            key = item.name
            sig = ctx.fn_sigs[key]
            fnty = ir.FunctionType(_llvm_type(ctx, sig.ret), [_llvm_type(ctx, t) for t in sig.params])
            ctx.fn_map[key] = ir.Function(ctx.module, fnty, name=key)
        elif isinstance(item, FnDecl):
            key = item.symbol or item.name
            sig = ctx.fn_sigs[key]
            llvm_name = key
            if not freestanding and item.name == "main":
                llvm_name = "__astra_user_main"
                user_main_key = key
            fnty = ir.FunctionType(_llvm_type(ctx, sig.ret), [_llvm_type(ctx, t) for t in sig.params])
            ctx.fn_map[key] = ir.Function(ctx.module, fnty, name=llvm_name)
            if item.multiversion and ctx.cpu_dispatch and _is_multiversion_candidate(item):
                suffixes = _variant_suffixes("avx512" if ctx.cpu_target == "native" else ctx.cpu_target)
                ctx.multiversion_variants[key] = suffixes
                for suf in suffixes:
                    vkey = f"{key}__mv_{suf}"
                    vfn = ir.Function(ctx.module, fnty, name=f"{llvm_name}_{suf}")
                    _set_variant_attrs(vfn, suf)
                    ctx.fn_map[vkey] = vfn
            user_fns.append(item)

    return user_fns, user_main_key

def _compile_function(ctx: _ModuleCtx, item: FnDecl, overflow_mode: str, *, fn_key: str | None = None) -> None:
    key = fn_key or (item.symbol or item.name)
    sig = ctx.fn_sigs[item.symbol or item.name]
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

    for (pname, pty), arg in zip(item.params, fn_ir.args):
        ptype = _canonical_type(pty)
        ptr = b.alloca(_llvm_type(ctx, ptype), name=pname)
        b.store(arg, ptr)
        state.vars[pname] = ptr
        state.var_types[pname] = ptype

    sites: list[DeferStmt] = []
    _collect_defer_sites(item.body, sites)
    state.defer_sites = sites
    for i, site in enumerate(sites):
        cptr = b.alloca(ir.IntType(64), name=f"defer_cnt_{i}")
        b.store(ir.Constant(ir.IntType(64), 0), cptr)
        state.defer_counts[id(site)] = cptr

    for st in item.body:
        _compile_stmt(ctx, state, st, overflow_mode)
        if _is_terminated(state):
            break

    if not _is_terminated(state):
        b.branch(epilogue)

    b.position_at_end(epilogue)
    _emit_defer_epilogue(ctx, state, overflow_mode)

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
    cpu_dispatch: bool = False,
    cpu_target: str = "baseline",
) -> str:
    _init_llvm_once()

    # Ensure semantic annotations (symbols/inferred types) are present for direct backend use.
    analyze(prog, filename="<input>", freestanding=freestanding)

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
        cpu_dispatch=cpu_dispatch,
        cpu_target=cpu_target,
    )

    _build_structs(ctx, prog)
    user_fns, user_main_key = _declare_functions(ctx, prog, freestanding=freestanding)

    for fn in user_fns:
        base_key = fn.symbol or fn.name
        if base_key in ctx.multiversion_variants:
            for suf in ctx.multiversion_variants[base_key]:
                _compile_function(ctx, fn, overflow_mode, fn_key=f"{base_key}__mv_{suf}")
            _compile_multiversion_dispatcher(ctx, fn)
        else:
            _compile_function(ctx, fn, overflow_mode)

    if not freestanding:
        _emit_hosted_main_wrapper(ctx, user_main_key)

    mod = binding.parse_assembly(str(module))
    mod.verify()

    out = str(mod)
    return out if out.endswith("\n") else out + "\n"
