import re
from dataclasses import dataclass

TOKEN_RE = re.compile(r'''\s*(?:(//.*)|([A-Za-z_][A-Za-z0-9_]*)|(\d+)|("[^"\\]*(?:\\.[^"\\]*)*")|(->|==|!=|<=|>=|&&|\|\||[{}()<>;,=+\-*/]))''')
KEYWORDS = {"fn", "let", "return", "if", "else", "while"}

@dataclass
class Token:
    kind: str
    text: str
    pos: int


def lex(src: str) -> list[Token]:
    out = []
    i = 0
    while i < len(src):
        m = TOKEN_RE.match(src, i)
        if not m:
            if src[i].isspace():
                i += 1
                continue
            raise SyntaxError(f"Unexpected token at {i}: {src[i:i+20]}")
        i = m.end()
        comment, ident, number, string, sym = m.groups()
        if comment:
            continue
        if ident:
            kind = ident if ident in KEYWORDS else "IDENT"
            out.append(Token(kind, ident, i))
        elif number:
            out.append(Token("INT", number, i))
        elif string:
            out.append(Token("STR", string[1:-1], i))
        elif sym:
            out.append(Token(sym, sym, i))
    out.append(Token("EOF", "", i))
    return out
