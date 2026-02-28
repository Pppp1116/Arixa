# Safety Analysis

- Frontend rejects malformed syntax.
- Semantic phase rejects undefined symbols and unresolved function calls.
- Deterministic builds prevent dependency drift via lockfile and stable hashing.
- Runtime-generated code executes in Python sandbox context by default process boundary.
