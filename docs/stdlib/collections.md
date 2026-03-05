# std.collections

Source: `stdlib/collections.astra`

List API:

- `list_new()`
- `list_push(xs, value)`
- `list_get(xs, index)`
- `list_set(xs, index, value)`
- `list_len(xs)`

Map API:

- `map_new()`
- `map_has(m, key)`
- `map_get(m, key)`
- `map_set(m, key, value)`
- `map_get_or(m, key, fallback)`

These APIs are opaque-handle wrappers around runtime primitives.
