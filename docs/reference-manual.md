# Astra Reference Manual

## CLI
- `astra build <in> -o <out> [--target py|x86_64|native] [--emit-ir out.json] [--strict] [--freestanding]`
- `astra check <in> [--freestanding]`
- `astra run <in>`
- `astra test [--kind unit|integration|e2e]`
- `astra selfhost`
- `--target native` requires `nasm` + `ld`, and emits an x86-64 executable.

## Tooling
- `astpm init/add/lock`
- `astfmt <file>`
- `astlint <file>`
- `astdoc <in> -o <out>`
- `astlsp`
- `astdbg <py script>`
- `astprof <py script>`

## Standard library modules
- core, collections, io, net, serde, process, time, crypto
- syntax guide: `docs/language-syntax-book.md`

## Language conveniences
- `defer <expr>;`
- `drop <expr>;` (consumes value and runs destructor immediately)
- use `let _ = <expr>;` / `_ = <expr>;` to discard a value result
- option coalescing: `<a> ?? <b>` where `<a>: Option<T>`
- immutable bindings: `fixed name[: Type] = expr;`
- option literal: `none` (only valid in `Option<T>` context)
- bare expression statements must be `Void` or `Never`
- typed params/fields accept `name Type` and `name: Type` (canonical style is `name: Type`)
- specialization impls: `impl fn name(...) -> ... { ... }`
- compile-time execution: `comptime { ... }` (pure/deterministic subset)
- text/buffer core types: `String`/`Vec<T>` (stdlib owned types), `str`/`[T]` (unsized DSTs behind references), `Bytes = Vec<u8>`
- `[T]` is valid in practice as `&[T]` / `&mut [T]` (or other pointer-backed DST positions), not as a standalone sized value
- by-value slice params (e.g. `fn f(xs: [Int])`) are rejected; use `&[Int]` / `&mut [Int]`
- indexing (`v[i]`) is bounds-checked and traps/panics on OOB in safe code; `get(i)` returns `T?`
- direct `String`/`str` indexing is a type error; index byte buffers/slices instead
- borrow lifetimes are elided/inferred; returning a reference must tie to an input reference
- default ownership transfer is move; scalar numerics/`Bool`/shared refs are copy-by-default

## x86-64 backend contract
- ABI classes are explicit in backend lowering:
  - integer/pointer class (`Int`, fixed ints, `isize`/`usize`, refs, fn pointers)
  - SSE class (`Float`/`f32`/`f64`)
- Calling convention:
  - integer args: `rdi,rsi,rdx,rcx,r8,r9`, then stack
  - float args: `xmm0..xmm7`, then stack
  - return in `rax` (integer/pointer) or `xmm0` (float)
  - call sites align stack to 16 bytes before `call`
- Runtime ABI boundary for lowered builtins:
  - `astra_print_i64`, `astra_print_str`, `astra_alloc`, `astra_free`, `astra_panic`
- Structured `defer` lowering supports full expressions (LIFO at function exit), including loop-hit counting.
- Async/await declarations lower on x86 as direct native control flow.
- Non-scalar values lower as opaque pointer-sized ABI handles in native mode.
