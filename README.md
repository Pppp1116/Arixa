# Astra Language Ecosystem

Astra is a compact, self-hosted-oriented language ecosystem with a deterministic build toolchain, x86-64 code generation, package tooling, formatting/linting, docs generation, LSP, debugging, profiling, and batteries-included standard library wrappers.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
astra build examples/hello.astra -o build/hello.py
python build/hello.py
```

## Commands
- `astra`: compile/build/test/selfhost
- `astpm`: package manager
- `astfmt`: formatter
- `astlint`: linter
- `astdoc`: documentation generator
- `astlsp`: stdio LSP server
- `astdbg`: debugger (break/step/inspect)
- `astprof`: profiler
