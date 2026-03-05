# Astra

Astra is a compact programming language ecosystem with a full compiler pipeline, CLI tooling, language server support, and a batteries-included standard library.

## Main Features

- Deterministic builds with content-based caching.
- Multiple build targets: Python, LLVM IR, and native executables via `clang`.
- Static checking pipeline with parse, compile-time, and semantic diagnostics.
- Built-in tooling: formatter (`astfmt`), linter (`astlint`), doc generator (`astdoc`), package helper (`astpm`), LSP server (`astlsp`), debugger (`astdbg`), and profiler (`astprof`).
- Hosted and freestanding compilation modes.
- Standard library modules for core types, collections, I/O, networking, process control, serialization, crypto, and time.
- Runtime-backed builtin APIs that mirror stdlib entry points used by the current semantic/codegen pipeline.

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requirements:

- Python 3.11+
- `clang` for `--target native`
- `llvmlite` (installed via project dependencies) for LLVM backend

## Quick Example

`examples/hello_world.astra`:

```astra
fn main() -> Int {
    print("hello, astra");
    return 0;
}
```

Build and run:

```bash
astra check examples/hello_world.astra
astra build examples/hello_world.astra -o build/hello.py
python build/hello.py
```

## Documentation

- Full docs index: `docs/README.md`
- Language reference: `docs/language/`
- Standard library reference: `docs/stdlib/`
- Tooling and CLI docs: `docs/tooling/`
- Compiler internals: `docs/compiler/`
- Contributor/development docs: `docs/development/`

Current compiler behavior note:

- import paths are resolved and validated by semantic analysis.
- most callable stdlib-facing functions are currently surfaced through builtin names.

Top-level project docs:

- `ARCHITECTURE.md`
- `COMPILER_OVERVIEW.md`
- `BUILD_SYSTEM.md`
- `TESTING.md`
- `FORMATTING.md`
- `EDITOR_SETUP.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `ROADMAP.md`
