"""Utilities for parsing and validating integer type names and widths."""

from __future__ import annotations

INT_WIDTH_MIN = 1
INT_WIDTH_MAX = 128


def _parse_prefixed_width(text: str) -> tuple[bool, int] | None:
    if len(text) < 2:
        return None
    prefix = text[0]
    if prefix not in {"i", "u"}:
        return None
    digits = text[1:]
    # Restrict to ASCII decimal digits so Unicode numerals (e.g. ²) do not
    # pass `isdigit()` and later crash `int(...)`.
    if not digits.isascii() or not digits.isdigit():
        return None
    if digits.startswith("0"):
        return None
    return prefix == "i", int(digits)


def looks_like_prefixed_int(text: str) -> bool:
    """Execute the `looks_like_prefixed_int` routine.
    
    Parameters:
        text: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    if len(text) < 2:
        return False
    if text[0] not in {"i", "u"}:
        return False
    return text[1:].isdigit()


def prefixed_int_width_error(text: str, max_width: int = INT_WIDTH_MAX) -> str | None:
    """Execute the `prefixed_int_width_error` routine.
    
    Parameters:
        text: Input value used by this routine.
        max_width: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    if not looks_like_prefixed_int(text):
        return None
    parsed = _parse_prefixed_width(text)
    if parsed is None:
        return f"integer width must be between {INT_WIDTH_MIN} and {max_width}"
    _, bits = parsed
    if bits < INT_WIDTH_MIN or bits > max_width:
        return f"integer width must be between {INT_WIDTH_MIN} and {max_width}"
    return None


def parse_prefixed_int_type(text: str, max_width: int = INT_WIDTH_MAX) -> tuple[int, bool] | None:
    """Parse the `prefixed_int_type` grammar production from the token stream.
    
    Parameters:
        text: Input value used by this routine.
        max_width: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    parsed = _parse_prefixed_width(text)
    if parsed is None:
        return None
    signed, bits = parsed
    if bits < INT_WIDTH_MIN or bits > max_width:
        return None
    return bits, signed


def parse_int_type_name(name: str, max_width: int = INT_WIDTH_MAX) -> tuple[int, bool] | None:
    """Parse the `int_type_name` grammar production from the token stream.
    
    Parameters:
        name: Input value used by this routine.
        max_width: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    t = name.strip()
    if t in {"Int", "isize"}:
        return 64, True
    if t == "usize":
        return 64, False
    return parse_prefixed_int_type(t, max_width=max_width)


def is_int_type_name(name: str, max_width: int = INT_WIDTH_MAX) -> bool:
    """Return whether the input satisfies `is_int_type_name`.
    
    Parameters:
        name: Input value used by this routine.
        max_width: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    return parse_int_type_name(name, max_width=max_width) is not None


def int_storage_size(bits: int) -> int:
    """Execute the `int_storage_size` routine.
    
    Parameters:
        bits: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    return max(1, (bits + 7) // 8)


def int_storage_align(size: int) -> int:
    """Execute the `int_storage_align` routine.
    
    Parameters:
        size: Input value used by this routine.
    
    Returns:
        Value described by the function return annotation.
    """
    if size <= 1:
        return 1
    if size <= 2:
        return 2
    if size <= 4:
        return 4
    if size <= 8:
        return 8
    return 16
