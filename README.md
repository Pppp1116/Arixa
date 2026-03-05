# Astra Language Ecosystem

Astra is a compact language ecosystem with deterministic builds, Python and LLVM backends, package tooling, formatting/linting, docs generation, LSP, debugging/profiling, and a batteries-included stdlib.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
astra build examples/hello.astra -o build/hello.py
python build/hello.py
```

## Commands
- `astra`: build/run/check/test/fmt/doc (`selfhost` is currently an unavailable placeholder command)
- `astpm`: package manager
- `astfmt`: formatter
- `astlint`: linter
- `astdoc`: documentation generator
- `astlsp`: stdio LSP server
- `astdbg`: debugger (break/step/inspect)
- `astprof`: profiler

## Documentation
- `docs/TOUR.md`: quick language walkthrough
- `docs/SPEC_COMPLIANCE.md`: SPEC-to-implementation/test mapping
- `docs/DIAGNOSTICS.md`: stable `astra check --json` diagnostic codes

## Build options
- `astra build <in> -o <out> [--target py|llvm|native] [--emit-ir path.ll] [--strict] [--freestanding] [--profile debug|release] [--overflow trap|wrap|debug] [--triple <llvm-triple>]`
- `astra check <in> [--freestanding] [--overflow trap|wrap|debug] [--json]`
- `astra check --files <f1> <f2> ... [--freestanding] [--overflow ...] [--json]`
- `astra check --stdin [--stdin-filename name] [--freestanding] [--overflow ...] [--json]`
- `astra test [--kind unit|integration|e2e]`
- `astra fmt <files...> [--check]`
- `astra doc <in> -o <out>`
- `--target native` compiles/links LLVM IR into an executable via `clang` and a bundled portable runtime source (override path with `ASTRA_RUNTIME_C_PATH`).
- `--freestanding` enforces runtime-free semantics/codegen for LLVM/native outputs:
  - hosted/runtime builtins are rejected during semantic analysis
  - LLVM IR cannot reference `astra_*` runtime symbols or other external host symbols
  - `--target native --freestanding` requires `fn _start()`
  - freestanding container API is `vec_new`, `vec_from`, `vec_len`, `vec_get`, `vec_set`, `vec_push` (no hosted runtime shims)
- Native regression sweep: `pytest tests/test_build.py -k native` (requires `clang`).
- LSP diagnostics are produced by the same check pipeline used by `astra check` (stable codes/spans).

## Syntax notes
- Immutable locals use `fixed`, mutable/inferred locals use `let`.
- Preferred typed style is `name: Type` (legacy `name Type` still parses for params/fields).
- Module imports support both `import std.io;` and legacy `import stdlib::io;`.
- Path imports use string form: `import "relative/path";` (resolved relative to the importing file).
- Non-stdlib module imports resolve from nearest package root (`Astra.toml`) when present; otherwise from the importing file directory.
- Integer types support dynamic widths: `iN`/`uN` where `N` is `1..128` (`Int`/`isize`/`usize` still map to 64-bit).
- Integer literals support width suffixes (for example `15u4`, `3i7`).
- Optional values use `Option<T>` + `none` (with `T?` sugar); `Nil` is not a type.
- `Never` is coercible to any type; `return;` is valid only in `-> Void` functions.
- Explicit cast syntax: `expr as Type`.
- Layout/type queries: `sizeof(Type)`, `alignof(Type)`, `size_of(expr)`, `align_of(expr)`, `bitSizeOf(Type)`, `maxVal(Type)`, `minVal(Type)`.
- Width-aware integer bit builtins: `countOnes(x)`, `leadingZeros(x)`, `trailingZeros(x)`.
- Packed structs are supported via `@packed struct Name { ... }` (packed fields support integer widths up to language maximum `128`, plus `Bool`).
- Freestanding builds avoid hosted entrypoint assumptions and are suitable for kernels/runtime stubs.
- `defer expr;` runs cleanup logic at function exit.
- `a ?? b` coalesces `Option<T>` values (`a: Option<T>`, `b: T`).
- Range loops are supported as `for i in start..end { ... }` and `for i in start..=end { ... }`.
- `match` supports wildcard arm `_` (must be the last arm).
- `match` also supports bind patterns, enum variant patterns, and guarded arms (`if ...`).
- `impl fn` supports minimal generic `where` constraints (`Copy`, `Send`, `Sync`) for specialization selection.
- Expression statements may discard values of any type; `drop expr;` remains available for explicit immediate destruction-style intent.
- LLVM backend emits validated LLVM IR through `llvmlite` and native builds are performed by `clang`.
- `i128/u128` helper runtime symbols remain available in the portable runtime for trap/wrap hard-op behavior.
