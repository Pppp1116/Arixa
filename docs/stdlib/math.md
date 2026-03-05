# std.math

Source: `stdlib/math.astra`

Status: `stable` (pure helpers)

Functions:

- `min_int(a, b)`
- `max_int(a, b)`
- `clamp_int(x, lo, hi)`
- `abs_int(x)`

Backend support:

- Python backend: supported
- Native backend (LLVM + runtime): supported
- Freestanding mode: supported

Pure helpers valid in hosted and freestanding mode.

Current limits:

- Integer-only helpers
- No transcendental/float math API yet
