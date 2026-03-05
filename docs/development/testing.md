# Development Testing Guide

Core commands:

```bash
pytest -q
make test
```

Targeted runs:

```bash
pytest tests/test_parser.py -q
pytest tests/test_semantic.py -q
pytest tests/test_build.py -k native -q
```

For CLI behavior:

```bash
astra check examples/hello_world.astra
astra build examples/hello_world.astra -o build/hello.py
```
