# Build System

## Project Build Metadata

Build metadata is defined in `pyproject.toml`:

- package: `astra-lang`
- Python requirement: `>=3.11`
- scripts: `astra`, `astpm`, `astfmt`, `astlint`, `astdoc`, `astlsp`, `astdbg`, `astprof`
- package data: bundled stdlib and runtime C asset

## Compiler Build Command

Main command:

```bash
astra build <input> -o <output> [--target py|llvm|native] [--kind exe|lib]
```

Useful flags:

- `--freestanding`
- `--strict`
- `--profile debug|release`
- `--overflow trap|wrap|debug`
- `--emit-ir <path>`
- `--triple <llvm-triple>`

## Build Caching

Cache file: `.astra-cache.json`.

Fingerprints include source imports, compiler source hashes, stdlib/runtime assets, and selected build flags.

## Makefile Targets

- `make venv`
- `make fmt`
- `make fmt-check`
- `make lint`
- `make test`
- `make e2e`
- `make all`

## Environment Variables

- `ASTRA_STDLIB_PATH`: override stdlib root
- `ASTRA_RUNTIME_C_PATH`: override runtime C source for native linking
