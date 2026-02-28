# Getting Started

```bash
pip install -e ".[dev]"
astra check examples/hello.astra
astra build examples/hello.astra -o build/hello.py
python build/hello.py
```

Run tests:
```bash
pytest -q
```
