# Lexer

Implementation: `astra/lexer.py`

Responsibilities:

- scan source text into token stream
- preserve line/column metadata
- report lexical errors as error tokens/diagnostics
- support integer literal forms, suffixes, comments, and punctuation

Main API:

- `Token` dataclass
- `lex(src, filename=...)`
