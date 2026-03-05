# std.vec

Source: `stdlib/vec.astra`

Typed wrappers over vector builtins:

- `vec_new_typed<T>() -> Vec<T>`
- `vec_len_typed<T>(v) -> Int`
- `vec_push_typed<T>(v, value) -> Int`
- `vec_get_typed<T>(v, index) -> Option<T>`
