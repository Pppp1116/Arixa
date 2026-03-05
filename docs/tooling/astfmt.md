# astfmt

Formatter implementation: `astra/formatter.py`

Command form:

```bash
astfmt <files...>
```

Equivalent core CLI command:

```bash
astra fmt <files...>
```

Config sources (nearest parent directory lookup):

- `astfmt.toml`
- `Astra.toml`

Supported keys:

- `indent_width`
- `line_width`
