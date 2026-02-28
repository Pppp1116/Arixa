# Releases

## v0.2.0
- Major language/toolchain completion pass.
- Added `extern`, `async`, and `await` syntax with semantic/codegen support on Python backend.
- Added structured diagnostics (`LEX`, `PARSE`, `SEM`, `CODEGEN`, `PKG`) and stricter semantic checks.
- Added `astra check`, `astra build --emit-ir`, `astra build --strict`, and `astra test --kind`.
- Added `--freestanding` for `build` and `check`, plus freestanding x86 entrypoint support.
- Replaced x86_64 stub with executable subset backend and explicit unsupported-feature diagnostics.
- Expanded stdlib wrappers (collections/io/net/serde/crypto/process/time).
- Reworked package manager to TOML-based manifest parsing and deterministic lock output.
- Improved formatter/linter/docgen/LSP behavior and expanded test coverage.
- Fixed editable installs and added `dev` optional dependencies.

## v0.1.0
- Initial end-to-end Astra ecosystem release.
- Deterministic build cache, package lockfile, and developer tooling included.
