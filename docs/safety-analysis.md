# Safety Analysis

- Frontend rejects malformed syntax.
- Semantic phase rejects undefined symbols and unresolved function calls.
- LLVM/native lowering inserts runtime traps for integer division/modulo by zero and signed overflow (`MIN / -1`, `MIN % -1`).
- LLVM/native float-to-int casts lower to saturating conversions to avoid poison/undefined behavior.
- LLVM/native `Any` values are tagged and checked at cast boundaries (box/unbox helpers), preventing raw-bit reinterpretation in safe code.
- `unsafe fn` calls require explicit unsafe context (`unsafe fn` or `unsafe { ... }`).
- `spawn` enforces Send/Sync-style constraints in semantic analysis for safe code.
- Deterministic builds prevent dependency drift via lockfile and stable hashing.
- Runtime-generated code executes in Python sandbox context by default process boundary.
- Ownership-inspired checks for `alloc`/`free` handles prevent use-after-free, double-free, use-after-move, and obvious leaks at semantic-analysis time.
