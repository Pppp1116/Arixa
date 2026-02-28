# Installation (Linux)

```bash
git clone <repo>
cd bitmask-calcOPT
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Verify:
```bash
astra build examples/hello.astra -o build/hello.py
python build/hello.py
```
