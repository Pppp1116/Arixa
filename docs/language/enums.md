# Enums

Enums model sum types with variants that may carry payloads.

Example:

```astra
enum Message {
    Quit,
    Write(String),
}
```

Enums are commonly paired with `match` for exhaustive branch handling.
