# Pattern Matching

Astra uses `match expr { ... }` with arm syntax `pattern => { ... }`.

Supported patterns include:

- literals
- names
- wildcard `_` (must be last arm)

Matching is validated during semantic analysis.
