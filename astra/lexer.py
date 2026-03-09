"""Lexer for converting Astra source text into tokens."""

from dataclasses import dataclass

from astra.int_types import INT_WIDTH_MAX, INT_WIDTH_MIN, parse_prefixed_int_type, prefixed_int_width_error

KEYWORDS = {
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
    "as",
    "sizeof",
    "alignof",
    "f16",
    "f80",
    "f128",
    "pub",
    "const",
    "true",
    "false",
    "where",
    "for",
    "async",
    "await",
}

MULTI_TOKENS = [
    "...",
    "::",
    "=>",
    "->",
    "==",
    "!=",
    "<=",
    ">=",
    "&&",
    "||",
    "??",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "<<=",
    ">>=",
    "&=",
    "|=",
    "^=",
    "<<",
    ">>",
    "..=",
    "..",
]

SINGLE_TOKENS = set("{}()<>;,=+-*/%!?[]:.&|^~@")


@dataclass
class Token:
    """Data container used by lexer.
    
    This type is part of Astra's public compiler/tooling surface.
    """
    kind: str
    text: str
    pos: int
    line: int
    col: int


def _advance_pos(text: str, line: int, col: int) -> tuple[int, int]:
    for ch in text:
        if ch == "\n":
            line += 1
            col = 1
        else:
            col += 1
    return line, col


def _scan_digits_with_separators(src: str, i: int, *, base: int) -> tuple[int, bool]:
    j = i
    saw_digit = False
    saw_invalid_sep = False
    prev_sep = False
    while j < len(src):
        ch = src[j]
        if ch == "_":
            if not saw_digit or prev_sep:
                saw_invalid_sep = True
            prev_sep = True
            j += 1
            continue
        if base == 2:
            is_digit = ch in {"0", "1"}
        elif base == 8:
            is_digit = ch in {"0", "1", "2", "3", "4", "5", "6", "7"}
        elif base == 10:
            is_digit = ch.isdigit()
        elif base == 16:
            is_digit = ch.isdigit() or ch.lower() in {"a", "b", "c", "d", "e", "f"}
        else:
            is_digit = False
        if not is_digit:
            break
        saw_digit = True
        prev_sep = False
        j += 1
    if prev_sep:
        saw_invalid_sep = True
    return j, saw_digit and not saw_invalid_sep


def lex(src: str, filename: str = "<input>") -> list[Token]:
    """Tokenize source text into Astra lexer tokens.
    
    Parameters:
        src: Astra source text to process.
        filename: Filename context used for diagnostics or path resolution.
    
    Returns:
        Value described by the function return annotation.
    """
    out: list[Token] = []
    i = 0
    line = 1
    col = 1
    while i < len(src):
        ch = src[i]
        if ch.isspace():
            i += 1
            if ch == "\n":
                line += 1
                col = 1
            else:
                col += 1
            continue

        start_i, start_line, start_col = i, line, col

        if src.startswith("///", i):
            j = i + 3
            while j < len(src) and src[j] != "\n":
                j += 1
            text = src[i + 3 : j].strip()
            out.append(Token("DOC_COMMENT", text, start_i, start_line, start_col))
            line, col = _advance_pos(src[i:j], line, col)
            i = j
            continue

        if src.startswith("//", i):
            j = i + 2
            while j < len(src) and src[j] != "\n":
                j += 1
            line, col = _advance_pos(src[i:j], line, col)
            i = j
            continue

        if src.startswith("#", i):
            j = i + 1
            while j < len(src) and src[j] != "\n":
                j += 1
            line, col = _advance_pos(src[i:j], line, col)
            i = j
            continue

        if src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j == -1:
                out.append(Token("ERROR", "unterminated block comment", start_i, start_line, start_col))
                break
            text = src[i : j + 2]
            line, col = _advance_pos(text, line, col)
            i = j + 2
            continue

        if src.startswith('"""', i):
            j = src.find('"""', i + 3)
            if j == -1:
                out.append(Token("ERROR", "unterminated multiline string", start_i, start_line, start_col))
                break
            raw = src[i + 3 : j]
            out.append(Token("STR_MULTI", raw, start_i, start_line, start_col))
            text = src[i : j + 3]
            line, col = _advance_pos(text, line, col)
            i = j + 3
            continue

        if ch == '"':
            j = i + 1
            escaped = False
            has_interpolation = False
            while j < len(src):
                c = src[j]
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '{' and not escaped:
                    # Check if this is an escaped brace ({{)
                    if j + 1 < len(src) and src[j + 1] == '{':
                        # Skip the escaped brace - it's a literal, not interpolation
                        j += 1  # Skip the second {
                    else:
                        # This is a real interpolation marker
                        has_interpolation = True
                elif c == '"':
                    break
                j += 1
            if j >= len(src) or src[j] != '"':
                out.append(Token("ERROR", "unterminated string", start_i, start_line, start_col))
                break
            raw = src[i + 1 : j]
            if has_interpolation:
                out.append(Token("STR_INTERP", raw, start_i, start_line, start_col))
            else:
                out.append(Token("STR", raw, start_i, start_line, start_col))
            text = src[i : j + 1]
            line, col = _advance_pos(text, line, col)
            i = j + 1
            continue

        if ch == "'":
            j = i + 1
            escaped = False
            while j < len(src):
                c = src[j]
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == "'":
                    break
                j += 1
            if j >= len(src) or src[j] != "'":
                out.append(Token("ERROR", "unterminated char", start_i, start_line, start_col))
                break
            raw = src[i + 1 : j]
            out.append(Token("CHAR", raw, start_i, start_line, start_col))
            text = src[i : j + 1]
            line, col = _advance_pos(text, line, col)
            i = j + 1
            continue

        if ch.isdigit() or (ch == "." and i + 1 < len(src) and src[i + 1].isdigit()):
            j = i
            kind = "INT"
            valid = True
            if ch == ".":
                kind = "FLOAT"
                j += 1
                j, valid = _scan_digits_with_separators(src, j, base=10)
            elif ch == "0" and i + 1 < len(src) and src[i + 1] in {"x", "X", "b", "B", "o", "O"}:
                base_ch = src[i + 1].lower()
                if base_ch == "x":
                    base = 16
                elif base_ch == "b":
                    base = 2
                else:
                    base = 8
                j = i + 2
                j, valid = _scan_digits_with_separators(src, j, base=base)
            else:
                j, valid = _scan_digits_with_separators(src, j, base=10)
                if j < len(src) and src[j] == "." and not src.startswith("..", j):
                    kind = "FLOAT"
                    j += 1
                    j, frac_valid = _scan_digits_with_separators(src, j, base=10)
                    valid = valid and frac_valid
                # Handle scientific notation (e/E) for both INT and FLOAT
                if kind in {"INT", "FLOAT"} and j < len(src) and src[j] in {"e", "E"}:
                    kind = "FLOAT"
                    j += 1
                    # Handle optional + or - after e/E
                    if j < len(src) and src[j] in {"+", "-"}:
                        j += 1
                    # Must have at least one digit after e/E
                    exp_start = j
                    j, exp_valid = _scan_digits_with_separators(src, j, base=10)
                    valid = valid and exp_valid and (j > exp_start)
            
            # Check for type suffix (123i64, 456u32, etc.)
            if kind == "INT" and j < len(src) and src[j] in {"i", "u"}:
                # Check if this is a valid type suffix
                suffix_start = j
                number_text = src[i:suffix_start]
                j += 1
                # Scan the digits for the type suffix
                j, suffix_valid = _scan_digits_with_separators(src, j, base=10)
                if suffix_valid and j > suffix_start + 1:  # Must have at least one digit
                    suffix = src[suffix_start:j]
                    # Validate the suffix
                    width_str = suffix[1:]  # Remove the 'i' or 'u' prefix
                    if width_str.startswith("0"):
                        out.append(
                            Token(
                                "ERROR",
                                f"integer width must be between {INT_WIDTH_MIN} and {INT_WIDTH_MAX}",
                                suffix_start,
                                start_line,
                                start_col + (suffix_start - start_i),
                            )
                        )
                    else:
                        width = int(width_str)
                        if width < INT_WIDTH_MIN or width > INT_WIDTH_MAX:
                            out.append(
                                Token(
                                    "ERROR",
                                    f"integer width must be between {INT_WIDTH_MIN} and {INT_WIDTH_MAX}",
                                    suffix_start,
                                    start_line,
                                    start_col + (suffix_start - start_i),
                                )
                            )
                        else:
                            # Emit as `<INT><INT_TYPE>` so parser/backend logic remains consistent.
                            out.append(Token("INT", number_text, start_i, start_line, start_col))
                            out.append(
                                Token(
                                    "INT_TYPE",
                                    suffix,
                                    suffix_start,
                                    start_line,
                                    start_col + (suffix_start - start_i),
                                )
                            )
                    text = src[i:j]
                    line, col = _advance_pos(text, line, col)
                    i = j
                    continue
                else:
                    # Invalid suffix, treat as regular integer
                    j = suffix_start
            
            text = src[i:j]
            if valid:
                out.append(Token(kind, text, start_i, start_line, start_col))
            else:
                out.append(Token("ERROR", f"invalid numeric literal {text}", start_i, start_line, start_col))
            line, col = _advance_pos(text, line, col)
            i = j
            continue

        # Handle arbitrary precision integer literals (i123, u456).
        # Keep this narrow so identifiers like `i2c_init` still lex as IDENT.
        if ch in {"i", "u"} and i + 1 < len(src) and src[i + 1].isdigit():
            j = i + 1
            # Scan the digits
            j, valid = _scan_digits_with_separators(src, j, base=10)
            text = src[i:j]
            if j < len(src) and (src[j].isalnum() or src[j] == "_"):
                # Fall through to IDENT lexing.
                pass
            elif valid and j > i + 1:  # Must have at least one digit
                int_width_err = prefixed_int_width_error(text, max_width=INT_WIDTH_MAX)
                if int_width_err is not None:
                    out.append(Token("ERROR", int_width_err, start_i, start_line, start_col))
                else:
                    out.append(Token("ARBITRARY_INT_TYPE", text, start_i, start_line, start_col))
                line, col = _advance_pos(text, line, col)
                i = j
                continue
            elif valid or text:
                out.append(Token("ERROR", f"invalid arbitrary precision integer type: {text}", start_i, start_line, start_col))
                line, col = _advance_pos(text, line, col)
                i = j
                continue

        if ch.isalpha() or ch == "_":
            j = i + 1
            while j < len(src) and (src[j].isalnum() or src[j] == "_"):
                j += 1
            text = src[i:j]
            if text in {"true", "false"}:
                out.append(Token("BOOL", text, start_i, start_line, start_col))
            else:
                int_width_err = prefixed_int_width_error(text, max_width=INT_WIDTH_MAX)
                if int_width_err is not None:
                    out.append(Token("ERROR", int_width_err, start_i, start_line, start_col))
                elif parse_prefixed_int_type(text, max_width=INT_WIDTH_MAX) is not None:
                    out.append(Token("INT_TYPE", text, start_i, start_line, start_col))
                else:
                    kind = text if text in KEYWORDS else "IDENT"
                    out.append(Token(kind, text, start_i, start_line, start_col))
            line, col = _advance_pos(text, line, col)
            i = j
            continue

        matched = None
        for tok in MULTI_TOKENS:
            if src.startswith(tok, i):
                matched = tok
                break
        if matched is not None:
            out.append(Token(matched, matched, start_i, start_line, start_col))
            line, col = _advance_pos(matched, line, col)
            i += len(matched)
            continue

        if ch in SINGLE_TOKENS:
            out.append(Token(ch, ch, start_i, start_line, start_col))
            i += 1
            col += 1
            continue

        out.append(Token("ERROR", ch, start_i, start_line, start_col))
        i += 1
        col += 1

    out.append(Token("EOF", "", i, line, col))
    return out
