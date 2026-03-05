# Compiler Overview

## Entry Points

- `astra build ...` -> `astra.build.build`
- `astra check ...` -> `astra.check.run_check_source` / `run_check_paths`

## Compilation Stages

1. Lexing
2. Parsing into AST nodes (`astra.ast` dataclasses)
3. Compile-time execution (`comptime {}`) in `astra.comptime`
4. Semantic analysis and type checking in `astra.semantic`
5. Loop lowering and optimization (`for_lowering`, `optimizer`)
6. Backend emission:
   - Python source (`astra.codegen.to_python`)
   - LLVM IR (`astra.llvm_codegen.to_llvm_ir`)
   - Native binary (`clang` link step from LLVM IR)

## Diagnostics

- Parse, comptime, and semantic diagnostics are normalized by `astra.check`.
- CLI can emit human text or JSON (`astra check --json`).

## Build Caching

`astra.build` computes a content fingerprint from:

- target profile/options
- transitive imported source files
- stdlib/runtime assets
- Astra toolchain source hashes

If fingerprint matches, build returns `cached`.

## Strict Mode

`--strict` validates backend-lowerable node/operator subsets before emission.

## Native Backend Notes

- Requires `clang`.
- Uses bundled runtime C source unless overridden by `ASTRA_RUNTIME_C_PATH`.
- `--kind exe` requires `main` (hosted) or `_start` (freestanding).
