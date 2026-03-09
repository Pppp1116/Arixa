# Safety Rules

GPU kernels are intentionally restricted.

Disallowed in `gpu fn`:
- async/await
- `comptime`, `unsafe` blocks
- host runtime builtins (I/O, filesystem, networking, process, dynamic containers)
- calling non-GPU functions
- unsupported local/parameter types (for example `String`, `Vec<T>`, `Any`, references)

Allowed in `gpu fn`:
- scalar math and comparisons
- loops and branching
- indexing and writing through `GpuMutSlice<T>`
- reads from `GpuSlice<T>`
- GPU-safe structs composed of GPU-safe fields

Compiler diagnostics are emitted during semantic analysis when rules are violated.
