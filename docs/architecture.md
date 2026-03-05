# Architecture Overview

1. Frontend: lexer -> parser -> AST.
2. Middle-end: semantic validation -> IR lowering -> optimizer.
3. Backends:
   - Python backend (primary, broad hosted language support including extern shims).
   - x86-64 backend (native executable backend with scalar + aggregate pointer lowering and runtime ABI integration).
4. Build orchestration: deterministic hashing + incremental cache.
5. Tools: formatter, linter, docgen, package manager, LSP, debugger, profiler.
