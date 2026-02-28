# Astra Language Ecosystem

Astra is a compact language ecosystem with deterministic builds, Python and x86-64 backends, package tooling, formatting/linting, docs generation, LSP, debugging/profiling, and a batteries-included stdlib.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
astra build examples/hello.astra -o build/hello.py
python build/hello.py
```

## Commands
- `astra`: build/run/check/test/selfhost
- `astpm`: package manager
- `astfmt`: formatter
- `astlint`: linter
- `astdoc`: documentation generator
- `astlsp`: stdio LSP server
- `astdbg`: debugger (break/step/inspect)
- `astprof`: profiler

## Build options
- `astra build <in> -o <out> [--target py|x86_64] [--emit-ir path.json] [--strict] [--freestanding]`
- `astra check <in> [--freestanding]`
- `astra test [--kind unit|integration|e2e]`

## Syntax notes
- Immutable locals use `fixed`, mutable/inferred locals use `let`.
- Preferred typed style is `name: Type` (legacy `name Type` still parses for params/fields).
- Integer-width aliases are available: `i8/u8/i16/u16/i32/u32/i64/u64/i128/u128/isize/usize`.
- Freestanding builds avoid hosted entrypoint assumptions and are suitable for kernels/runtime stubs.
- `defer expr;` runs cleanup logic at function exit.
- `a ?? b` is a null-coalescing operator for concise fallback values.
