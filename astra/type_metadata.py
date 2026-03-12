"""Shared primitive type metadata for compiler and tooling layers."""

from __future__ import annotations

from astra.float_types import STANDARD_FLOAT_TYPES

# Float names are sourced from the float type registry.
FLOAT_TYPES = set(STANDARD_FLOAT_TYPES.keys())

# Core primitive inventory used by parser/semantics/tooling.
PRIMITIVES = {
    "Int",
    "isize",
    "usize",
    "Float",
    "String",
    "str",
    "Bool",
    "Any",
    "Void",
    "Never",
    "Bytes",
}
PRIMITIVES.update(FLOAT_TYPES)

# Scalar-by-value primitives used by ownership/escape checks.
COPY_SCALAR_TYPES = {"Float", "Bool", *FLOAT_TYPES}
