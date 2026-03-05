# std.collections

Source: `stdlib/collections.astra`

Status: `experimental` (dynamic container wrappers)

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

Backend support:

- Python backend: supported
- Native backend (LLVM + runtime): supported
- Freestanding mode: not supported

Current limits:

- Values are `Any`-typed at API boundary
- No iterator traits or generic container abstractions
- No advanced containers (`BTreeMap`, `Deque`, `Set`, priority queue)
