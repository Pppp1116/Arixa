# std.atomic

Source: `stdlib/atomic.astra`

Status: `experimental` (hosted compatibility API)

Types:

- `AtomicInt`

Functions:

- `atomic_int_new(v) -> AtomicInt`
- `atomic_load(&AtomicInt) -> Int`
- `atomic_store(&mut AtomicInt, v) -> Int`
- `atomic_fetch_add(&mut AtomicInt, delta) -> Int`
- `atomic_compare_exchange(&mut AtomicInt, expected, desired) -> Bool`

Notes:

- Current implementation is not hardware-atomic; it provides a stable API surface.
