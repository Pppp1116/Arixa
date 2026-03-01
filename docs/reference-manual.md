# Astra Reference Manual

## CLI
- `astra build <in> -o <out> [--target py|x86_64|native] [--emit-ir out.json] [--strict] [--freestanding] [--profile debug|release] [--overflow trap|wrap|debug]`
- `astra check <in> [--freestanding] [--overflow trap|wrap|debug]`
- `astra run <in>`
- `astra test [--kind unit|integration|e2e]`
- `astra selfhost`
- `--target native` requires `nasm` and a linker driver (`cc`/`gcc`/`clang`, fallback `ld`), and emits an x86-64 executable.

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
- explicit cast syntax is supported: `expr as Type`
- layout queries are supported:
  - `sizeof(Type)`, `alignof(Type)`
  - `size_of(expr)`, `align_of(expr)` (type-only; expression is not evaluated)
- numeric overflow control:
  - `build --profile debug|release` (default `debug`)
  - `build/check --overflow trap|wrap|debug`
  - `debug` overflow mode resolves to `trap` in debug profile, `wrap` in release profile

## x86-64 backend contract
- ABI classes are explicit in backend lowering:
  - integer/pointer class (`Int`, fixed ints, `isize`/`usize`, refs, fn pointers)
  - SSE class (`Float`/`f32`/`f64`)
  - 128-bit integer class (`i128`/`u128`) split as low/high 64-bit halves
- Calling convention:
  - integer args: `rdi,rsi,rdx,rcx,r8,r9`, then stack
  - float args: `xmm0..xmm7`, then stack
  - return in `rax` (integer/pointer) or `xmm0` (float)
  - call sites align stack to 16 bytes before `call`
- Runtime ABI boundary for lowered builtins:
  - `astra_print_i64`, `astra_print_str`, `astra_alloc`, `astra_free`, `astra_panic`
- 128-bit hard-op helper ABI (returns in `rax`/`rdx`):
  - multiply: `astra_i128_mul_{wrap|trap}`, `astra_u128_mul_{wrap|trap}`
  - division: `astra_i128_div_{wrap|trap}`, `astra_u128_div_{wrap|trap}`
  - modulo: `astra_i128_mod_{wrap|trap}`, `astra_u128_mod_{wrap|trap}`
  - args use split-eightbyte by-value halves: `a.low,a.high,b.low,b.high` in integer argument registers
  - division/modulo by zero always traps
- Structured `defer` lowering supports full expressions (LIFO at function exit), including loop-hit counting.
- Async/await declarations lower on x86 as direct native control flow.
- Non-scalar values lower as opaque pointer-sized ABI handles in native mode.
