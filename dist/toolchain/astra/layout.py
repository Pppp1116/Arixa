"""Type and struct layout computation used by semantics and code generation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from astra.ast import StructDecl, type_text
from astra.int_types import int_storage_align, int_storage_size, parse_int_type_name


class LayoutError(Exception):
    """Error type raised by the layout subsystem.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    pass


@dataclass(frozen=True)
class TypeLayout:
    """Data container used by layout.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    size: int
    align: int
    kind: str
    signed: bool | None
    bits: int
    queryable: bool
    opaque: bool = False


@dataclass(frozen=True)
class StructLayout:
    """Data container used by layout.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    size: int
    align: int
    field_offsets: dict[str, int]
    field_bit_offsets: dict[str, int]
    field_bits: dict[str, int]
    field_layouts: dict[str, TypeLayout]
    bits: int
    packed: bool = False


_SCALAR_LAYOUTS: dict[str, TypeLayout] = {
    "Bool": TypeLayout(1, 1, "int", False, 8, True),
    "f32": TypeLayout(4, 4, "float", None, 32, True),
    "f64": TypeLayout(8, 8, "float", None, 64, True),
    "Float": TypeLayout(8, 8, "float", None, 64, True),
    "Void": TypeLayout(0, 1, "void", None, 0, False),
    "Never": TypeLayout(0, 1, "void", None, 0, False),
}


def align_to(value: int, align: int) -> int:
    """Execute the `Execute the function.` function.
    
    Parameters:
        value: Input value used by this function.
        align: Input value used by this function.
    
    Returns:
        Value described by the function return annotation.
    """
    if align <= 1:
        return value
    rem = value % align
    return value if rem == 0 else value + (align - rem)


def canonical_type(typ: str) -> str:
    """Execute the `Execute the function.` function.
    
    Parameters:
        typ: Input value used by this function.
    
    Returns:
        Value described by the function return annotation.
    """
    t = type_text(typ).strip()
    if t == "Bytes":
        return "Vec<u8>"
    if t.startswith("&mut "):
        return f"&mut {canonical_type(t[5:])}"
    if t.startswith("&"):
        return f"&{canonical_type(t[1:])}"
    if t.endswith("?"):
        return f"Option<{canonical_type(t[:-1])}>"
    if t.startswith("Option<") and t.endswith(">"):
        return f"Option<{canonical_type(t[7:-1])}>"
    if t.startswith("Vec<") and t.endswith(">"):
        return f"Vec<{canonical_type(t[4:-1])}>"
    if t.startswith("[") and t.endswith("]"):
        return f"[{canonical_type(t[1:-1])}]"
    return t


def _is_option_type(typ: str) -> bool:
    return typ.startswith("Option<") and typ.endswith(">")


def _is_vec_type(typ: str) -> bool:
    return typ.startswith("Vec<") and typ.endswith(">")


def _is_slice_type(typ: str) -> bool:
    return typ.startswith("[") and typ.endswith("]")


def _is_fn_type(typ: str) -> bool:
    return typ.startswith("fn(")


def _is_unsized_value_type(typ: str) -> bool:
    return typ == "str" or _is_slice_type(typ)


def layout_of_type(
    typ: str,
    structs: Mapping[str, StructDecl],
    mode: str = "codegen",
    _cache: dict[str, StructLayout] | None = None,
    _stack: set[str] | None = None,
) -> TypeLayout:
    """Execute the `Execute the function.` function.
    
    Parameters:
        typ: Input value used by this function.
        structs: Input value used by this function.
        mode: Input value used by this function.
        _cache: Input value used by this function.
        _stack: Input value used by this function.
    
    Returns:
        Value described by the function return annotation.
    """
    c = canonical_type(typ)
    if c in _SCALAR_LAYOUTS:
        return _SCALAR_LAYOUTS[c]
    int_info = parse_int_type_name(c)
    if int_info is not None:
        bits, signed = int_info
        size = int_storage_size(bits)
        align = int_storage_align(size)
        return TypeLayout(size, align, "int", signed, bits, True)
    if c.startswith("&"):
        return TypeLayout(8, 8, "ptr", False, 64, True)
    if _is_fn_type(c):
        return TypeLayout(8, 8, "fnptr", False, 64, True)
    if _is_unsized_value_type(c):
        if mode == "query":
            raise LayoutError(f"unsized type {c} is not queryable by value")
        return TypeLayout(8, 8, "ptr", False, 64, False, opaque=True)
    if c in {"Any", "String"} or _is_option_type(c) or _is_vec_type(c):
        if mode == "query":
            raise LayoutError(f"opaque type {c} is not queryable")
        return TypeLayout(8, 8, "ptr", False, 64, False, opaque=True)
    if c in structs:
        s_layout = layout_of_struct(c, structs, mode=mode, _cache=_cache, _stack=_stack)
        return TypeLayout(s_layout.size, s_layout.align, "struct", None, s_layout.bits, True)
    if mode == "query":
        raise LayoutError(f"unknown type {c} for layout query")
    return TypeLayout(8, 8, "ptr", False, 64, False, opaque=True)


def layout_of_struct(
    name: str,
    structs: Mapping[str, StructDecl],
    mode: str = "codegen",
    _cache: dict[str, StructLayout] | None = None,
    _stack: set[str] | None = None,
) -> StructLayout:
    """Execute the `Execute the function.` function.
    
    Parameters:
        name: Input value used by this function.
        structs: Input value used by this function.
        mode: Input value used by this function.
        _cache: Input value used by this function.
        _stack: Input value used by this function.
    
    Returns:
        Value described by the function return annotation.
    """
    cache = _cache if _cache is not None else {}
    if name in cache:
        return cache[name]
    stack = _stack if _stack is not None else set()
    if name in stack:
        raise LayoutError(f"recursive layout is unsupported for struct {name}")
    decl = structs.get(name)
    if decl is None:
        raise LayoutError(f"unknown struct type {name}")
    stack.add(name)
    if decl.packed:
        bit_offset = 0
        field_offsets: dict[str, int] = {}
        field_bit_offsets: dict[str, int] = {}
        field_bits: dict[str, int] = {}
        field_layouts: dict[str, TypeLayout] = {}
        for field_name, field_ty in decl.fields:
            lay = layout_of_type(field_ty, structs, mode=mode, _cache=cache, _stack=stack)
            bits = 1 if canonical_type(field_ty) == "Bool" else lay.bits
            field_offsets[field_name] = bit_offset // 8
            field_bit_offsets[field_name] = bit_offset
            field_bits[field_name] = bits
            field_layouts[field_name] = lay
            bit_offset += bits
        size = max(1, (bit_offset + 7) // 8) if decl.fields else 0
        out = StructLayout(
            size=size,
            align=1,
            field_offsets=field_offsets,
            field_bit_offsets=field_bit_offsets,
            field_bits=field_bits,
            field_layouts=field_layouts,
            bits=bit_offset,
            packed=True,
        )
    else:
        offset = 0
        struct_align = 1
        field_offsets = {}
        field_bit_offsets = {}
        field_bits = {}
        field_layouts = {}
        for field_name, field_ty in decl.fields:
            lay = layout_of_type(field_ty, structs, mode=mode, _cache=cache, _stack=stack)
            offset = align_to(offset, lay.align)
            field_offsets[field_name] = offset
            field_bit_offsets[field_name] = offset * 8
            field_bits[field_name] = lay.bits
            field_layouts[field_name] = lay
            offset += lay.size
            if lay.align > struct_align:
                struct_align = lay.align
        size = align_to(offset, struct_align)
        out = StructLayout(
            size=size,
            align=struct_align,
            field_offsets=field_offsets,
            field_bit_offsets=field_bit_offsets,
            field_bits=field_bits,
            field_layouts=field_layouts,
            bits=size * 8,
            packed=False,
        )
    cache[name] = out
    stack.remove(name)
    return out
