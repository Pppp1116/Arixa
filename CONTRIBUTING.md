# Contributing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Running tests

```bash
pytest -q
pytest -q --cov=astra --cov-report=term-missing
```

Property tests and mutation tests are part of CI:

```bash
pytest -q tests/test_property_fuzz.py
mutmut run --max-children 1
```

## Making changes

- Prefer small, focused PRs.
- Include tests for behavior changes.
- Keep `--freestanding` constraints in mind: avoid introducing new mandatory runtime symbols unless gated to hosted mode.

## Reporting issues

Include:

- OS + Python version
- `clang --version` (native builds)
- a minimal `.astra` repro, expected vs actual output
