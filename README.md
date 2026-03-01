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
- `astra build <in> -o <out> [--target py|x86_64|native] [--emit-ir path.json] [--strict] [--freestanding] [--profile debug|release] [--overflow trap|wrap|debug]`
- `astra check <in> [--freestanding] [--overflow trap|wrap|debug]`
- `astra test [--kind unit|integration|e2e]`
- `--target native` assembles/links x86-64 output into an executable (requires `nasm` and a linker driver such as `cc`/`gcc`/`clang`, fallback `ld`).

## Syntax notes
- Immutable locals use `fixed`, mutable/inferred locals use `let`.
- Preferred typed style is `name: Type` (legacy `name Type` still parses for params/fields).
- Integer-width aliases are available: `i8/u8/i16/u16/i32/u32/i64/u64/i128/u128/isize/usize`.
- Optional values use `Option<T>` + `none` (with `T?` sugar); `Nil` is not a type.
- `Never` is coercible to any type; `return;` is valid only in `-> Void` functions.
- Explicit cast syntax: `expr as Type`.
- Layout query expressions: `sizeof(Type)`, `alignof(Type)`, `size_of(expr)`, `align_of(expr)`.
- Freestanding builds avoid hosted entrypoint assumptions and are suitable for kernels/runtime stubs.
- `defer expr;` runs cleanup logic at function exit.
- `a ?? b` coalesces `Option<T>` values (`a: Option<T>`, `b: T`).
- Bare expression statements must be `Void`/`Never`; use `drop expr;` to discard other values.
- x86-64 backend now uses an explicit ABI lowering table (integer/pointer vs SSE classes), stack args beyond register limits, indirect fn-pointer calls, and runtime ABI symbols for lowered builtins.
- `i128/u128` are supported end-to-end on x86-64 with split register returns (`rax`/`rdx`) and runtime helper ABI for hard ops (`mul/div/mod`).
