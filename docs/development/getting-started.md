# Installation (Linux)

```bash
git clone <repo>
cd programming-language-
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Requirements:
- `clang` for `--target native`
- `llvmlite` (installed via project dependency) for LLVM IR generation
- bundled stdlib/runtime assets are installed with the `astra-lang` module (override paths with `ASTRA_STDLIB_PATH` / `ASTRA_RUNTIME_C_PATH` if needed)

Verify:
```bash
astra check examples/hello.astra
astra build examples/hello.astra -o build/hello.py
python build/hello.py
astra build examples/hello.astra -o build/hello.native --target native
./build/hello.native
pytest tests/test_build.py -k native
```
