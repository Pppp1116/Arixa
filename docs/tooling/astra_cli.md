# astra CLI

CLI implementation: `astra/cli.py`

## `astra check`

Validate source without building output artifacts.

```bash
astra check <input>
astra check --files file1.astra file2.astra
astra check --stdin --stdin-filename demo.astra
```

Flags:

- `--json`
- `--freestanding`
- `--overflow trap|wrap|debug`

Expected output:

- success: `ok` (or `ok (N files)`)
- failure: diagnostics on stderr and exit code 1

## `astra build`

```bash
astra build <input> -o <output> [--target py|llvm|native] [--kind exe|lib]
```

Additional flags:

- `--emit-ir <path>`
- `--strict`
- `--freestanding`
- `--profile debug|release`
- `--overflow trap|wrap|debug`
- `--triple <llvm-triple>`

Expected output: `built` or `cached`.

## `astra run`

Build Python target into `.astra-build/<stem>.py` and execute it:

```bash
astra run program.astra arg1 arg2
```

## `astra fmt`

```bash
astra fmt file1.astra file2.astra
astra fmt --check file1.astra
```

Expected output:

- in-place mode: `formatted`
- check mode: `ok` or `not formatted: <file>` with exit code 1

## `astra test`

```bash
astra test --kind unit
astra test --kind integration
astra test --kind e2e
```

Uses `pytest -q` under the hood with `-k` filters.
