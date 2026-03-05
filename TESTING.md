# Testing

## Test Framework

Astra uses `pytest` for unit, integration, and end-to-end validation.

## Main Commands

```bash
pytest -q
pytest -q --cov=astra --cov-report=term-missing
```

CLI wrapper command:

```bash
astra test --kind unit
astra test --kind integration
astra test --kind e2e
```

## Specialized Suites

- Property-based tests: `tests/test_property_fuzz.py`
- Native backend coverage: `pytest tests/test_build.py -k native`
- LSP/tooling tests: `tests/test_lsp_server.py`, `tests/test_tools.py`

## Expected Baseline

Before opening a PR:

1. `make fmt-check`
2. `make lint`
3. `make test`

## Test Data

- `examples/` and `benchmarks/` provide language-level fixtures.
- `tests/` contains phase-specific checks (lexer/parser/semantic/codegen/tooling).
