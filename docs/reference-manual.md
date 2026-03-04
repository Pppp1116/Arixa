# Astra Reference Manual

## CLI surface

### `astra build`
- Form:
  - `astra build <in> -o <out> [--target py|llvm|native] [--emit-ir out.ll] [--strict] [--freestanding] [--profile debug|release] [--overflow trap|wrap|debug] [--triple <llvm-triple>] [--verbose] [--profile-compile] [--profile-json] [--threads N]`
- Behavior notes:
  - Runs parse -> comptime -> semantic -> optimization -> backend.
  - `--target py` writes Python source.
  - `--target llvm` writes LLVM IR text.
  - `--target native` compiles via `clang` to an executable.
  - `--emit-ir` forces IR generation even for `--target py`.
  - `--strict` enables strict backend-lowering validation and rejects unsupported AST forms for strict mode.
  - `--verbose` prints build state (`built` / `cached`) for tool integration.

### `astra check`
- Forms:
  - `astra check <in> [--freestanding] [--overflow trap|wrap|debug] [--json]`
  - `astra check --files <f1> <f2> ... [--freestanding] [--overflow ...] [--json]`
  - `astra check --stdin [--stdin-filename name] [--freestanding] [--overflow ...] [--json]`
- Input mode is exclusive; exactly one of positional `<in>`, `--files`, `--stdin` is required.
- `--json` returns `{ok, files_checked, diagnostics[]}` with phase/code/span/notes suitable for machine parsing.

### `astra run`
- Form:
  - `astra run <in> [args...] [--profile-compile] [--profile-json] [--threads N]`
- Always builds with Python backend to `.astra-build/<stem>.py` and executes via current Python interpreter.
- `--profile-json` is currently accepted for CLI flag consistency but `run` does not emit a dedicated JSON payload.

### `astra bench`
- Form:
  - `astra bench <in> -o <out> [--target py|llvm|native] [--emit-ir out.ll] [--strict] [--freestanding] [--profile debug|release] [--overflow trap|wrap|debug] [--triple <llvm-triple>] [--profile-compile] [--profile-json] [--threads N]`
- Bench mode specifics:
  - Runs 3 cold builds (cache is cleared each run).
  - Forces compile profiling on each run (the `--profile-compile` flag is effectively redundant in `bench`).
  - Prints normal build logs for each run, then prints median per-phase and total timings as a trailing JSON object on stdout.
  - `--profile-json` is currently accepted for flag parity but does not change bench output format.

### Other `astra` subcommands
- `astra test [--kind unit|integration|e2e]`
- `astra fmt <files...> [--check]`
- `astra doc <in> -o <out>`
- `astra selfhost` (placeholder only; exits with `selfhost-unavailable` message)

## Tool entrypoints

- `astpm init/add/lock`
- `astfmt <file>`
- `astlint <file>`
- `astdoc <in> -o <out>`
- `astlsp`
- `astdbg <py script>`
- `astprof <py script>`

LSP diagnostics are aligned with `astra check` output formatting and code taxonomy.


## Module and stdlib resolution

- Import forms:
  - `import std.io;`
  - `import stdlib::io;` (legacy)
  - `import "relative/path";`
- Resolution behavior:
  - `std.*` / `stdlib::*` resolve from stdlib root lookup order.
  - Non-stdlib module imports resolve from nearest package root containing `Astra.toml`; fallback is importing file directory.
  - String/path imports resolve relative to importing file (or absolute if given).
- Stdlib root lookup order:
  1. `ASTRA_STDLIB_PATH`
  2. repository `stdlib/`
  3. bundled package `astra/stdlib`

## Build internals and cache contract

- Cache file: `.astra-cache.json`.
- Fingerprint inputs include:
  - entry file contents and transitive file graph,
  - target,
  - strict/freestanding flags,
  - presence of `emit_ir`,
  - profile,
  - resolved overflow mode,
  - target triple.
- Cached reuse requires both matching fingerprint and existing output path.

## Backend contract (low-level)

### Shared frontend/midend invariants
- All backends receive AST after:
  1. parser span attachment,
  2. comptime evaluation,
  3. semantic checks,
  4. optimization passes.
- Diagnostics preserve phase-prefixed reporting (`PARSE`/`SEM`/`CODEGEN` etc.) and source spans.

### Python backend (`--target py`)
- Emits Python runtime scaffolding for builtins and stdlib-adjacent helpers.
- Maintains language evaluation ordering in generated expressions.
- Implements runtime helpers in emitted Python for:
  - allocation primitives (`alloc`, `free`),
  - task primitives (`spawn`, `join`),
  - vector/list/map helpers,
  - IO/network/process/time glue,
  - bit intrinsics (`countOnes`, `leadingZeros`, `trailingZeros`, `rotl`, `rotr`).

### LLVM backend (`--target llvm`)
- Requires `llvmlite` availability.
- Emits validated LLVM IR with explicit control-flow blocks for:
  - short-circuit boolean ops,
  - `??` coalescing,
  - `if`/`while`/`for`/`match`,
  - defer epilogue sequencing.
- Overflow behavior is selected by resolved overflow mode (`trap`/`wrap`).

### Native backend (`--target native`)
- Uses `clang`; missing `clang` is a CODEGEN error.
- Hosted link line includes generated IR + runtime C + `-lm`.
- Freestanding link line uses:
  - `-nostdlib`
  - `-nostartfiles`
  - linker entrypoint override `-Wl,-e,_start`
- After successful link, output file is marked executable (`chmod +x` behavior).

## Runtime ABI symbols (hosted native/LLVM)

Hosted builds may reference runtime C symbols including (non-exhaustive):

- Core:
  - `astra_print_i64`
  - `astra_print_str`
  - `astra_alloc`
  - `astra_free`
  - `astra_panic`
- 128-bit hard-op helpers:
  - `astra_i128_mul_{wrap|trap}` / `astra_u128_mul_{wrap|trap}`
  - `astra_i128_div_{wrap|trap}` / `astra_u128_div_{wrap|trap}`
  - `astra_i128_mod_{wrap|trap}` / `astra_u128_mod_{wrap|trap}`

## Freestanding hard constraints

`--freestanding` is not just a hint; it is enforced:

1. Semantic phase rejects hosted/runtime builtins.
2. IR validation rejects forbidden runtime symbol dependencies (`astra_*`, `__astra_*` except freestanding-internal prefixes).
3. IR validation rejects non-LLVM external declarations.
4. Native freestanding requires explicit `_start` function.

Freestanding vector API expected by lowering:
- `vec_new`, `vec_from`, `vec_len`, `vec_get`, `vec_set`, `vec_push`.

## Language conveniences and semantic notes

- `defer <expr>;` executes at function exit in LIFO order.
- `drop <expr>;` explicit consumption/destructor intent.
- Coalesce operator: `<a> ?? <b>` with `<a>: Option<T>` and `<b>: T`.
- `none` only valid in `Option<T>` context.
- Expression statements can discard any value type.
- Canonical typed syntax uses `name: Type` (`name Type` remains accepted where supported).
- `comptime { ... }` executes deterministic/pure subset during compile.
- `Any` on LLVM/native is tagged dynamic value:
  - implicit upcast `T -> Any`,
  - explicit cast required for `Any -> T`.
- Unsafe boundary:
  - `unsafe fn`, `unsafe { ... }`, and unsafe-call-site rules.
- Integer model:
  - dynamic-width `iN`/`uN` (`N=1..128`),
  - typed literals (`15u4`, `3i7`),
  - width-aware intrinsics and rotate helpers.
- Layout/type queries:
  - `sizeof`, `alignof`, `size_of`, `align_of`, `bitSizeOf`, `maxVal`, `minVal`.
