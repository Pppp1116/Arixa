# std.atomic

Source: `stdlib/atomic.astra`

Status: `partial` (runtime-backed API)

Types:

- `AtomicInt`

Functions:

- `atomic_int_new(v) -> AtomicInt`
- `atomic_load(&AtomicInt) -> Int`
- `atomic_store(&mut AtomicInt, v) -> Int`
- `atomic_fetch_add(&mut AtomicInt, delta) -> Int`
- `atomic_compare_exchange(&mut AtomicInt, expected, desired) -> Bool`

Notes:

- Native runtime uses real atomic operations with sequential consistency.
- Python backend uses a lock-backed implementation for deterministic behavior.
