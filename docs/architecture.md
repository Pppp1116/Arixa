# Architecture Overview

1. Frontend: lexer -> parser -> AST.
2. Middle-end: semantic validation -> IR lowering -> optimizer.
3. Backends: Python transpilation backend and baseline x86-64 assembly backend.
4. Build orchestration: deterministic hashing + incremental cache.
5. Tools: formatter, linter, docgen, package manager, LSP, debugger, profiler.
