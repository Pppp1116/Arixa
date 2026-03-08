"""Utilities for parsing and validating standard IEEE float type names."""

from __future__ import annotations

# Standard IEEE float types supported by ASTRA
STANDARD_FLOAT_TYPES = {
    "f16": 16,
    "f32": 32, 
    "f64": 64,
    "f80": 80,
    "f128": 128
}


def parse_standard_float_type(text: str) -> int | None:
    """Parse standard IEEE float type and return bit width.
    
    Parameters:
        text: Float type name (e.g., "f16", "f32", "f64", "f80", "f128")
    
    Returns:
        Bit width if valid standard float type, None otherwise
    """
    return STANDARD_FLOAT_TYPES.get(text.strip())


def is_standard_float_type(text: str) -> bool:
    """Check if text is a valid standard IEEE float type.
    
    Parameters:
        text: Float type name to check
    
    Returns:
        True if valid standard float type, False otherwise
    """
    return text.strip() in STANDARD_FLOAT_TYPES


def float_storage_size(bits: int) -> int:
    """Get storage size in bytes for float bit width.
    
    Parameters:
        bits: Float bit width
    
    Returns:
        Storage size in bytes
    """
    if bits == 16:
        return 2
    elif bits == 32:
        return 4
    elif bits == 64:
        return 8
    elif bits == 80:
        return 10  # Extended precision uses 10 bytes
    elif bits == 128:
        return 16
    else:
        raise ValueError(f"Unsupported float bit width: {bits}")


def float_storage_align(bits: int) -> int:
    """Get storage alignment in bytes for float bit width.
    
    Parameters:
        bits: Float bit width
    
    Returns:
        Storage alignment in bytes
    """
    if bits == 16:
        return 2
    elif bits == 32:
        return 4
    elif bits == 64:
        return 8
    elif bits == 80:
        return 2  # Extended precision uses 2-byte alignment
    elif bits == 128:
        return 16
    else:
        raise ValueError(f"Unsupported float bit width: {bits}")


def is_native_llvm_float_type(bits: int) -> bool:
    """Check if float type is natively supported by LLVM.
    
    Parameters:
        bits: Float bit width
    
    Returns:
        True if natively supported by LLVM, False if software emulation needed
    """
    return bits in {16, 32, 64}
