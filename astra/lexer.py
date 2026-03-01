from dataclasses import dataclass

from astra.int_types import INT_WIDTH_MAX, parse_prefixed_int_type, prefixed_int_width_error

KEYWORDS = {
    "fn",
    "let",
    "fixed",
    "return",
    "if",
    "else",
    "while",
    "for",
    "break",
    "continue",
    "struct",
    "enum",
    "type",
    "import",
    "mut",
    "pub",
    "extern",
    "async",
    "await",
    "unsafe",
    "impl",
    "match",
    "defer",
    "drop",
    "comptime",
    "none",
    "in",
    "as",
    "sizeof",
    "alignof",
}

MULTI_TOKENS = [
    "&&=",
    "||=",
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
    "..",
]

SINGLE_TOKENS = set("{}()<>;,=+-*/%!?[]:.&|^~@")


@dataclass
class Token:
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


def lex(src: str, filename: str = "<input>") -> list[Token]:
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
            while j < len(src):
                c = src[j]
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    break
                j += 1
            if j >= len(src) or src[j] != '"':
                out.append(Token("ERROR", "unterminated string", start_i, start_line, start_col))
                break
            raw = src[i + 1 : j]
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
            has_dot = False
            while j < len(src) and src[j].isdigit():
                j += 1
            if j < len(src) and src[j] == "." and not src.startswith("..", j):
                has_dot = True
                j += 1
                while j < len(src) and src[j].isdigit():
                    j += 1
            text = src[i:j]
            kind = "FLOAT" if has_dot else "INT"
            out.append(Token(kind, text, start_i, start_line, start_col))
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
