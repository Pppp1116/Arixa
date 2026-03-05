# Freestanding vs Hosted

## Hosted Mode (default)

- Runtime-backed I/O/process/network helpers are available.
- Entry point for executables: `fn main() -> Int`.

## Freestanding Mode (`--freestanding`)

- Hosted runtime symbols are disallowed.
- LLVM/native output must not reference host/runtime externs.
- Entry point for executables: `fn _start()`.

Use freestanding mode for kernels, low-level runtimes, or environments without host services.
