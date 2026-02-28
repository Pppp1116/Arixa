# Safety Analysis

- Frontend rejects malformed syntax.
- Semantic phase rejects undefined symbols and unresolved function calls.
- Deterministic builds prevent dependency drift via lockfile and stable hashing.
- Runtime-generated code executes in Python sandbox context by default process boundary.
- Ownership-inspired checks for `alloc`/`free` handles prevent use-after-free, double-free, use-after-move, and obvious leaks at semantic-analysis time.
