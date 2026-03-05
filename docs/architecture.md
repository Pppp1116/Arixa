# Architecture Overview

1. Frontend: lexer -> parser -> AST.
2. Middle-end: semantic validation -> IR lowering -> optimizer.
3. Native/LLVM pipeline: `parse -> semantic -> IR -> value_specialization -> codegen(multiversion) -> layout_optimizer -> link` (value/layout/multiversion optimizers enabled via profile-guided build flags).
4. Backends:
   - x86-64/native backend (primary backend; intended to support full language feature parity, including async/await lowering and runtime ABI integration).
   - Python backend (secondary/dev backend used for fast iteration and tooling flows).
5. Build orchestration: deterministic hashing + incremental cache.
6. Tools: formatter, linter, docgen, package manager, LSP, debugger, profiler.
