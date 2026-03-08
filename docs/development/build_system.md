# Build System

## Project Build Metadata

Build metadata is defined in `pyproject.toml`:

- module: `arixa-lang`
- Python requirement: `>=3.11`
- scripts: `arixa`, `arpm`, `arfmt`, `arlint`, `ardoc`, `arlsp`, `ardbg`, `arprof`
- module data: bundled stdlib and runtime C asset

## Compiler Build Command

Main command:

```bash
arixa build <input> -o <output> [--target py|llvm|native] [--kind exe|lib]
```

Useful flags:

- `--freestanding`
- `--strict`
- `--profile debug|release`
- `--overflow trap|wrap|debug`
- `--emit-ir <path>`
- `--triple <llvm-triple>`

## Build Caching

Cache file: `.arixa-cache.json`.

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

- `ARIXA_STDLIB_PATH`: override stdlib root
- `ARIXA_RUNTIME_C_PATH`: override runtime C source for native linking
