# Architecture Overview

1. Frontend: lexer -> parser -> AST.
2. Middle-end: semantic validation -> IR lowering -> optimizer.
3. Backends:
   - Python backend (primary, full language support including async/await and extern shims).
   - x86-64 backend (executable integer subset with explicit unsupported-feature diagnostics).
4. Build orchestration: deterministic hashing + incremental cache.
5. Tools: formatter, linter, docgen, package manager, LSP, debugger, profiler.
