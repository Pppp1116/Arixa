# Releases

## v0.3.1
- Removed semantic/backend packed-field hard cap of 64 bits; `@packed struct` supports integer field widths up to language max (`128`).
- Generalized LLVM packed lowering to dynamic byte windows (including windows wider than 128 bits for offset-packed `u128` fields).
- Expanded comptime execution support with `match` statement handling and indirect function-value calls, with clearer `undefined/non-function/non-pure` diagnostics.
- Expanded formatter statement coverage for `defer` and `comptime`, replacing fallback `/* unsupported */` output for valid syntax.
- Improved semantic call diagnostics to report explicit non-function call type errors.

## v0.3.0
- Replaced handwritten x86-64 backend with LLVM IR backend (`llvmlite`) and removed custom tuple-IR pipeline.
- Added `llvm` build target and `--triple` support for LLVM/native builds.
- Changed `--emit-ir` to emit textual LLVM IR (`.ll`).
- Reworked native pipeline to `clang` + portable runtime C implementation (`runtime/llvm_runtime.c`).
- Removed x86 runtime assembly source and x86-specific backend API (`to_x86_64`).

## v0.2.2
- Added dynamic-width integer language support across lexer/parser/semantic/codegen (`iN`/`uN`, `N=1..128`) including literal suffixes (for example `15u4`).
- Added `@packed struct` support with packed layout tracking and packed-field x86-64 access/update lowering.
- Added type/integer intrinsics: `bitSizeOf(T)`, `maxVal(T)`, `minVal(T)`, `countOnes(x)`, `leadingZeros(x)`, `trailingZeros(x)`.
- Added width-aware diagnostics for invalid integer widths, `i1` hinting, and implicit integer-width conversions requiring explicit casts.

## v0.2.1
- Expanded x86-64/native backend coverage:
  - Added linked Linux x86-64 runtime object for native builds (`astra_print_*`, `astra_alloc/free`, `astra_panic`).
  - Added native lowering for `match`, `await`, broader `defer` forms (including loops), and pointer-deref assignments.
  - Added aggregate pointer-handle lowering for struct/dynamic values across calls/returns.
  - Added struct constructor/field lowering and array/slice index + `.get()` lowering paths.
- Build/cache reliability improvements:
  - Cache fingerprint now includes transitive imported source contents, stdlib/runtime/toolchain stamp, and build-mode dimensions.
  - Strict mode now performs structural backend-AST validation instead of scanning generated text for `"pass\\n"`.
- Added end-to-end native regression tests for runtime symbols and expanded x86 codegen coverage.

## v0.2.0
- Major language/toolchain completion pass.
- Added `extern`, `async`, and `await` syntax with semantic/codegen support on Python backend.
- Added structured diagnostics (`LEX`, `PARSE`, `SEM`, `CODEGEN`, `PKG`) and stricter semantic checks.
- Added `arixa check`, `arixa build --emit-ir`, `arixa build --strict`, and `arixa test --kind`.
- Added `--freestanding` for `build` and `check`, plus freestanding x86 entrypoint support.
- Replaced x86_64 stub with executable subset backend and explicit unsupported-feature diagnostics.
- Expanded stdlib wrappers (collections/io/net/serde/crypto/process/time).
- Reworked module manager to TOML-based manifest parsing and deterministic lock output.
- Improved formatter/linter/docgen/LSP behavior and expanded test coverage.
- Fixed editable installs and added `dev` optional dependencies.

## v0.1.0
- Initial end-to-end Arixa ecosystem release.
- Deterministic build cache, module lockfile, and developer tooling included.
