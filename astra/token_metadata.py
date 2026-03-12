"""Central token/keyword metadata shared by lexer and parser."""

from __future__ import annotations

from astra.float_types import STANDARD_FLOAT_TYPES

# Core language keywords that are not auto-derived from type families.
KEYWORDS_CORE = frozenset(
    {
        "fn",
        "mut",
        "if",
        "else",
        "while",
        "for",
        "match",
        "return",
        "break",
        "continue",
        "unreachable",
        "unsafe",
        "struct",
        "enum",
        "trait",
        "type",
        "import",
        "extern",
        "comptime",
        "none",
        "set",
        "in",
        "is",
        "as",
        "sizeof",
        "alignof",
        "pub",
        "const",
        "true",
        "false",
        "where",
        "async",
        "await",
    }
)

# Float type tokens come from the compiler float type registry.
FLOAT_TYPE_KEYWORDS = frozenset(STANDARD_FLOAT_TYPES.keys())

# Unified lexer keyword inventory.
LEXER_KEYWORDS = frozenset(KEYWORDS_CORE | FLOAT_TYPE_KEYWORDS)

# Parser type-start token kinds; float tokens are accepted dynamically by kind/text.
TYPE_START_BASE_KINDS = frozenset({"IDENT", "INT_TYPE", "ARBITRARY_INT_TYPE", "none", "*", "&", "[", "fn"})


def is_float_type_keyword(kind: str) -> bool:
    return kind in FLOAT_TYPE_KEYWORDS


def is_type_start_token(kind: str) -> bool:
    return kind in TYPE_START_BASE_KINDS or is_float_type_keyword(kind)


def is_type_atom_token(kind: str) -> bool:
    return kind in {"IDENT", "ARBITRARY_INT_TYPE", "INT_TYPE", "none"} or is_float_type_keyword(kind)

