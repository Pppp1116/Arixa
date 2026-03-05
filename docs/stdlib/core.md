# std.core

Source: `stdlib/core.astra`

Public types:

- `Option<T>` with variants `None` and `Some(T)`
- `Result<T, E>` with variants `Ok(T)` and `Err(E)`
- `type Bytes = Vec<u8>`

Public functions:

- `add_checked(a, b) -> Option<Int>`
- `sub_checked(a, b) -> Option<Int>`
- `mul_checked(a, b) -> Option<Int>`
- `div_checked(a, b) -> Option<Int>`
- `rem_checked(a, b) -> Option<Int>`
- `shl_checked(a, n) -> Option<Int>`
- `shr_checked(a, n) -> Option<Int>`

These helpers return `none` for invalid operations (overflow/invalid shift/division by zero cases).
