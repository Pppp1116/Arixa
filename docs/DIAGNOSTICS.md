# Astra Diagnostic Codes

This table documents the stable codes emitted by `astra check --json`.

## Lex (`LEX`)

| Code | Meaning |
| --- | --- |
| `ASTRA-LEX-0001` | Unterminated string literal |
| `ASTRA-LEX-0002` | Unterminated character literal |
| `ASTRA-LEX-0003` | Unterminated block comment |
| `ASTRA-LEX-0004` | Invalid numeric literal |
| `ASTRA-LEX-9999` | Other lexer diagnostic |

## Parse (`PARSE`)

| Code | Meaning |
| --- | --- |
| `ASTRA-PARSE-0001` | Expected-token parse error (`expected ...`) |
| `ASTRA-PARSE-0002` | Unexpected token/atom parse error |
| `ASTRA-PARSE-0003` | Unexpected EOF during parsing |
| `ASTRA-PARSE-9999` | Other parser diagnostic |

## Semantic (`SEM`)

| Code | Meaning |
| --- | --- |
| `ASTRA-TYPE-0001` | Type mismatch |
| `ASTRA-MOD-0001` | Import/module resolution failure |
| `ASTRA-NAME-0001` | Undefined name |
| `ASTRA-NAME-0002` | Undefined function |
| `ASTRA-ENTRY-0001` | Missing entrypoint (`main` or `_start`, depending on build mode) |
| `ASTRA-CFG-0001` | Control-flow misuse (for example `break`/`continue` outside loops) |
| `ASTRA-COMPTIME-0001` | Compile-time execution error |
| `ASTRA-SEM-9999` | Other semantic diagnostic |

## Notes

- Codes are assigned in `astra/check.py` (`_code_for`).
- Type mismatch diagnostics include structured notes (`context`, `expected`, `got`) when available.
