# astlsp

LSP server implementation: `astra/lsp.py`

Capabilities include:

- diagnostics (parse and semantic)
- hover
- go to definition
- references
- document symbols
- completion snippets
- formatting

Diagnostics are aligned with `astra check` via shared checking paths.

Run:

```bash
astlsp
```

It communicates via stdio using JSON-RPC/LSP framing.
