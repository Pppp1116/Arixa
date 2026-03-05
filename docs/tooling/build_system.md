# Tooling Build System Notes

Build orchestration for compiler outputs is implemented in `astra/build.py` and exposed through `astra build`.

Key behaviors:

- transitive import fingerprinting
- build cache reuse via `.astra-cache.json`
- optional LLVM IR emission (`--emit-ir`)
- native linking through `clang` when `--target native`

See also:

- `BUILD_SYSTEM.md`
- `docs/compiler/code_generation.md`
