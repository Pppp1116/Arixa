# Astra Diagnostic Codes

Stable diagnostics are emitted by `astra check` and `astra check --json`.

## Error Codes

| Code | Meaning |
| --- | --- |
| `E0001` | Syntax error (generic lexer/parser) |
| `E0002` | Unexpected token |
| `E0003` | Unexpected end of input |
| `E0004` | Unterminated block comment |
| `E0005` | Invalid numeric literal |
| `E0100` | Type mismatch |
| `E0101` | Invalid numeric/operator type usage |
| `E0102` | Wrong number of function arguments |
| `E0103` | Missing required return |
| `E0104` | Illegal assignment to immutable binding |
| `E0105` | Attempted call on non-function value |
| `E0110` | Invalid pattern match arm |
| `E0111` | Non-exhaustive pattern match |
| `E0200` | Unknown identifier |
| `E0201` | Unknown function |
| `E0202` | Import/module resolution failure |
| `E0203` | Unknown field |
| `E0204` | Missing required field |
| `E0300` | Missing/invalid punctuation |
| `E0301` | Missing semicolon |
| `E0302` | Invalid control-flow syntax usage |
| `E0400` | Borrowing rule violation |
| `E0401` | Use-after-move |
| `E0402` | Use-after-free |
| `E0403` | Owned allocation leak |
| `E0500` | Unsafe context required |
| `E0501` | Hosted API used in freestanding mode |
| `E0600` | Invalid or missing program entrypoint |
| `E0700` | Compile-time execution error |
| `E0701` | Integer overflow detected |
| `E9999` | Unknown/internal diagnostic fallback |

## Warning Codes

| Code | Meaning |
| --- | --- |
| `W0001` | Unreachable code |
| `W0002` | Unused variable |
| `W9999` | Unknown warning fallback |

## Notes

- Diagnostics are normalized in `astra/check.py`.
- Human output and JSON output use the same underlying diagnostics.
- LSP diagnostics reuse these codes and can expose quick fixes when a suggestion has an edit.

## Planned Diagnostic Expansion

Near-term diagnostics work is centered on:

- Trait coherence violations and generic resolution failures, including clearer candidate/bound mismatch notes.
- Pattern matching exhaustiveness and redundancy in deeper structural/nested forms.
- Lifetime/region reasoning notes that make borrow origin and outlives failures easier to trace.
