# Architecture Overview

## End-to-end pipeline

Astra compilation is a deterministic staged pipeline:

1. **Input discovery / module graph expansion**
   - Build starts from the provided entry file.
   - Imports are expanded to collect all reachable source files before analysis.
2. **Frontend**
   - Lexer + parser produce AST nodes with source spans.
3. **Comptime phase**
   - `comptime { ... }` blocks are evaluated before semantic analysis.
4. **Semantic analysis**
   - Type checking, ownership/flow constraints, builtin restrictions (including freestanding rules), and diagnostics.
5. **IR optimization**
   - Program IR/AST-level simplification/normalization passes run before backend emission.
6. **Backend emission**
   - `py`: Python source output.
   - `llvm`: LLVM IR text output.
   - `native`: LLVM IR + `clang` link to executable.

## Backend matrix

### Python backend (`--target py`)
- Emits runnable Python code.
- Used by `astra run` (which always builds to Python in `.astra-build/<stem>.py` then executes it).
- Includes runtime shims for language/runtime builtins in generated output.

### LLVM backend (`--target llvm`)
- Emits validated LLVM IR through `llvmlite`.
- Reuses the same frontend/comptime/semantic/optimizer pipeline as other targets.
- Supports explicit `--emit-ir` output in addition to normal target output.

### Native backend (`--target native`)
- First generates LLVM IR, then invokes `clang`.
- Hosted mode links the generated IR with bundled runtime C (`runtime/llvm_runtime.c` or `astra/assets/runtime/llvm_runtime.c`, overridable via `ASTRA_RUNTIME_C_PATH`).
- Freestanding mode uses `-nostdlib -nostartfiles -Wl,-e,_start` and requires a user `_start` entrypoint.

## Build system details

- **Deterministic fingerprinting + cache**:
  - Build cache key includes source path, target, strict/freestanding toggles, `emit_ir` presence, profile, resolved overflow mode, and target triple.
  - Cache is stored in `.astra-cache.json`; when fingerprint and output match, build returns `cached`.
- **Overflow resolution**:
  - `build --overflow debug` resolves to `trap` in debug profile and `wrap` in release profile.
- **Parallelization hooks**:
  - Multi-file builds may parse/analyze/optimize in parallel when parallel mode is enabled.
  - `--threads N` sets `ASTRA_THREADS` to control worker pool sizing.
- **Profiling hooks**:
  - `--profile-compile` enables per-phase timing.
  - `build` can emit profiling JSON to stderr with `--profile-json`; `bench` always emits JSON medians to stdout.

## Freestanding enforcement layers

Freestanding constraints are enforced at multiple stages:

1. **Semantic checks** reject hosted/runtime-only builtins in user code.
2. **IR symbol checks** reject generated LLVM with forbidden dependencies:
   - Runtime symbols with `astra_*` / `__astra_*` (except freestanding-prefixed internal helpers).
   - External non-LLVM declarations.
3. **Entrypoint check** for native freestanding (`fn _start()`).

## Tooling architecture (high-level)

- `astra`: orchestrates build/check/run/test/fmt/doc/bench.
- `astpm`: package manager entrypoint.
- `astfmt`, `astlint`, `astdoc`, `astlsp`, `astdbg`, `astprof`: dedicated tool binaries exposed by `pyproject` script entrypoints.
