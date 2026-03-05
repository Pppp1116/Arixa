# Contributing

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Optional native backend prerequisites:

- Install `clang` and ensure it is available in `PATH`.

## Contribution Workflow

1. Create a focused branch from `main`.
2. Make small, reviewable changes.
3. Add or update tests for behavior changes.
4. Run formatting, linting, and tests locally.
5. Open a pull request with motivation, implementation notes, and test evidence.

## Local Quality Checks

```bash
make fmt-check
make lint
make test
```

Or run tools directly:

```bash
astra fmt --check $(find . -name '*.astra' -print)
pytest -q
pytest -q --cov=astra --cov-report=term-missing
```

Additional suites used in CI:

```bash
pytest -q tests/test_property_fuzz.py
mutmut run --max-children 1
```

## VS Code Bundle Refresh

Before packaging the VS Code extension, refresh the bundled compiler/server snapshot:

```bash
python scripts/build_vscode_bundle.py
cd editors/vscode
npm run package
```

## Coding Expectations

- Preserve deterministic behavior in parser/semantic/codegen phases.
- Keep diagnostics stable and actionable.
- Avoid introducing hosted-only runtime dependencies into freestanding paths.
- Document public APIs and language-visible behavior.

## Pull Request Checklist

- [ ] Behavior is explained in code comments or docs.
- [ ] Public functions/types include docstrings or doc comments.
- [ ] New commands/flags are documented.
- [ ] Tests pass locally.

## Reporting Issues

Include:

- OS and Python version
- `clang --version` (if native build is involved)
- minimal `.astra` reproduction
- expected vs actual behavior
- full diagnostic output
