# Formatting

Astra formatting is provided by `astra fmt` / `astfmt` (`astra.formatter`).

## Defaults

- Indentation: 4 spaces
- Preferred line width: 100
- One blank line between top-level declarations
- Multi-line block style by default

## Commands

Format files in place:

```bash
astra fmt file1.astra file2.astra
```

Check mode:

```bash
astra fmt --check file1.astra file2.astra
```

## Configuration

Formatter config is discovered from nearest parent directory via:

- `astfmt.toml`
- `Astra.toml`

Supported keys:

- `indent_width` in `{2,4,8}`
- `line_width` (minimum practical value is 40)
