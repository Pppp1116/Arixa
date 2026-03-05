# Architecture

Astra is organized as a classic compiler pipeline plus toolchain commands around that pipeline.

## High-Level Layout

- Frontend: `astra/lexer.py`, `astra/parser.py`, `astra/ast.py`
- Semantic/type layer: `astra/semantic.py`, `astra/layout.py`, `astra/int_types.py`
- Transform/lowering: `astra/for_lowering.py`, `astra/comptime.py`, `astra/optimizer.py`
- Backends: `astra/codegen.py` (Python), `astra/llvm_codegen.py` (LLVM/native)
- Build/check orchestration: `astra/build.py`, `astra/check.py`, `astra/cli.py`
- Tooling: formatter, linter, docs generator, LSP, debugger, profiler

## Pipeline Diagram

```text
source (.astra)
    |
    v
lex -> parse -> AST
    |
    v
comptime execution
    |
    v
semantic analysis + type checks
    |
    v
lowering + optimization
    |
    +--> Python backend  -> .py artifact
    |
    +--> LLVM backend    -> .ll artifact
                     |
                     +--> native link (clang) -> executable/shared lib
```

## Hosted vs Freestanding

- Hosted mode allows runtime-backed builtins (`read_file`, process, sockets, etc.).
- Freestanding mode (`--freestanding`) forbids hosted runtime dependencies and enforces runtime-free output constraints for LLVM/native paths.

See `COMPILER_OVERVIEW.md` and `docs/compiler/architecture.md` for detailed stage behavior.
