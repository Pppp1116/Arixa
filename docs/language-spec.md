# Astra Formal Language Specification

## Syntax

Grammar (EBNF):

```
program   = { import_decl | type_decl | struct_decl | enum_decl | extern_fn | fn_decl } ;
import_decl = "import" (module_path | string) ["as" ident] [";"] ;
module_path = ident { ("." | "::") ident } ;
fn_decl   = ["pub"] ["async"] ["unsafe"] "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] [","] ")" [type] ["where" where_bound {"," where_bound}] block ;
extern_fn = ["unsafe"] "extern" string "fn" ident "(" [param {"," param}] ")" [type] ";" ;
param     = ["mut"] ident type ;
where_bound = ident ":" ident {"+" ident} ;
type      = postfix_type ;
postfix_type = primary_type ["?"] ;
primary_type = ident ["<" type {"," type} ">"]
             | "&" ["mut"] type
             | "[" type "]"
             | "fn" "(" [type {"," type}] ")" type
             | "(" type ")" ;
block     = "{" { stmt } [expr] "}" ;
stmt      = bind_stmt | set_stmt | comptime_stmt | defer_stmt | drop_stmt | return_stmt | if_stmt | while_stmt | for_stmt | match_stmt | assign_stmt | expr ";" ;
comptime_stmt = "comptime" block ;
bind_stmt = ["mut"] ident [":" type] "=" expr ";" ;
set_stmt  = "set" expr ("=" | "+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<=" | ">>=") expr ";" ;
defer_stmt = "defer" expr ";" ;
drop_stmt = "drop" expr ";" ;
return_stmt = "return" [expr] ";" ;
if_stmt   = "if" expr block ["else" block] ;
while_stmt = "while" expr block ;
for_stmt  = "for" ident "in" for_iterable block ;
for_iterable = range_iterable | expr ;
range_iterable = expr (".." | "..=") expr ;
assign_stmt = expr ("=" | "+=" | "-=" | "*=" | "/=" | "%=" | "&=" | "|=" | "^=" | "<<=" | ">>=") expr ";" ;
expr      = coalesce_expr ;
coalesce_expr = logic_or_expr { "??" logic_or_expr } ;
logic_or_expr = logic_and_expr { "||" logic_and_expr } ;
logic_and_expr = bit_or_expr { "&&" bit_or_expr } ;
bit_or_expr = bit_xor_expr { "|" bit_xor_expr } ;
bit_xor_expr = bit_and_expr { "^" bit_and_expr } ;
bit_and_expr = compare_expr { "&" compare_expr } ;
compare_expr = shift_expr { ("==" | "!=" | "<" | "<=" | ">" | ">=") shift_expr } ;
shift_expr = add_expr { ("<<" | ">>") add_expr } ;
add_expr  = mul_expr { ("+" | "-") mul_expr } ;
mul_expr  = unary_expr { ("*" | "/" | "%") unary_expr } ;
unary_expr = ["await"] ( ("-" | "!" | "~" | "*" | "&" ["mut"]) unary_expr | cast_expr ) ;
cast_expr = postfix_expr { "as" type } ;
postfix_expr = atom { "." ident | "[" expr "]" | "(" [expr {"," expr}] ")" | "!" } ;
atom      = int | float | string | typed_int | "none" | ident | "(" expr ")" | layout_query | type_query ;
typed_int = int int_type_tok ;
int_type_tok = ("i" | "u") nonzero_digit {digit} ;
layout_query = "sizeof" "(" type ")" | "alignof" "(" type ")" | "size_of" "(" expr ")" | "align_of" "(" expr ")" ;
type_query = "bitSizeOf" "(" type ")" | "maxVal" "(" type ")" | "minVal" "(" type ")" ;
```

Conventions:
- Parameter syntax is `name Type` (no `:`).
- Return type appears directly after `)` (no `->`).
- Return type is optional; omitted means `Void`.
- `@packed` is currently a recognized top-level attribute and is only valid on `struct` declarations.

## Semantics
- Call-by-value.
- Function scope with lexical bindings.
- Strict evaluation order left-to-right.
- Integer arithmetic/bitwise/shift operators require matching integer types.
- Mixed int/float arithmetic and comparison are rejected unless explicit cast (`expr as Type`) is used.
- Implicit conversion between different integer widths/signedness is rejected; explicit cast is required.
- Right shift semantics are type-directed:
  - signed integers: arithmetic shift
  - unsigned integers: logical shift
- Integer division/modulo in safe code trap on invalid operations:
  - divisor is zero
  - signed overflow case (`MIN / -1`, `MIN % -1`)
- Float-to-int casts are saturating (`NaN -> 0`, out-of-range clamps to destination bounds).
- Overflow mode is part of build/check configuration:
  - `check`: default `trap`
  - `build --profile debug`: default effective overflow `trap`
  - `build --profile release`: default effective overflow `wrap`
  - `--overflow trap|wrap|debug` overrides defaults (`debug` resolves by profile for `build`, and to `trap` for `check`)

## Memory model
- Ownership-first model for user data.
- Borrowed references are immutable unless uniquely owned.
- Runtime backend uses deterministic reference counting for managed objects.
- Core owned/borrowed buffers:
  - `String`: owned UTF-8 text (stdlib core type).
  - `str`: unsized UTF-8 text DST (typically as `&str`).
  - `Vec<T>`: owned, heap-backed growable sequence (stdlib core type; conceptually ptr/len/cap handle).
  - `[T]`: unsized slice DST (typically as `&[T]` or `&mut [T]`).
  - `Bytes`: alias of `Vec<u8>`.
- Borrowing `Vec<T>` yields slice views (`&[T]`, `&mut [T]`).

## Type system
- Nominal primitive types: `Int`, `Float`, `Bool`, `Any`, `Void`, `Never`.
- Integer families: `iN`/`uN` where `N` is in `1..128`, plus `isize`/`usize` aliases.
- Integer literals may carry width suffixes (for example `15u4`, `3i7`).
- Integer literals support decimal/hex/binary forms and `_` separators:
  - decimal: `1_000_000`
  - hex: `0xFF`, `0xffff_ffff`
  - binary: `0b1010_0101`
  - typed suffixes: `123u32`, `-1i64`
- Signed `i1` is rejected in semantic analysis with a hint suggesting `u1`.
- Invalid widths like `i0` or `u65536` are lexer errors.
- First-class union types: `A | B | C`.
- Stdlib core owned types: `String`, `Vec<T>`.
- Built-in bytes alias: `Bytes = Vec<u8>`.
- Built-in unsized DSTs: `str`, `[T]`.
- Parametric generics on function declarations (`fn id<T>(x T) T`).
- `T?` is syntax sugar for `T | none`.
- `none` has no standalone type; it is valid only where a nullable type is expected.
- `a ?? b` requires `a: T | none` and `b: T`, producing `T`.
- `??` is short-circuiting: the right operand is evaluated only when the left operand is `none`.
- `a!` propagates non-success union branches to the caller.
- Integer type queries:
  - `bitSizeOf(T)` returns logical bit width.
  - `maxVal(T)`/`minVal(T)` return integer bounds for integer type `T`.
- Width-aware integer bit intrinsics:
  - `countOnes(x)`, `leadingZeros(x)`, `trailingZeros(x)`.
  - aliases: `popcnt(x)`, `clz(x)`, `ctz(x)`.
  - rotate helpers: `rotl(x, n)`, `rotr(x, n)` (rotation count is modulo bit width).
- Nullable and error flows are modeled with unions and user-defined error types.
- Flow-sensitive type narrowing with `is` keyword: `if result is String { result.uppercase() }`
- Union types must be narrowed before use as specific members.
- `match` on union types is exhaustiveness-checked.
- `Never` is coercible to any type `T` (including `Void`).
- In type joins, `Never` acts as bottom: `join(Never, T) = T` and `join(Never, Never) = Never`.
- `Any` is a tagged dynamic value on native/LLVM backends.
- Implicit conversion is one-way (`T -> Any`); `Any -> T` requires explicit cast (`as T`).
- Casting between `Any` and reference/function-pointer types requires `unsafe` context.
- JSON conversion for `Any` is shape-stable:
  - objects roundtrip as map values
  - arrays roundtrip as list values
  - scalar JSON values roundtrip as scalar `Any` tags
- Expression statements may discard values of any type.
- `drop expr;` remains accepted for explicit consumption/destruction-style flows (legacy-compatible syntax).
- `return;` is valid only in functions returning `Void`.
- `return` is for early exit; a trailing expression returns implicitly from non-`Void` functions.
- `for` uses only `for <ident> in <iterable-expr> { ... }` syntax; C-style `for init; cond; step { ... }` is invalid.
- Supported `for` iterables are:
  - ranges: `start..end`, `start..=end`
  - `Vec<T>`
  - slices behind references (`&[T]`, `&mut [T]`)
  - `Bytes` (`Vec<u8>`)
- Unsized rules:
  - `str` is unsized; use behind references/pointers (for now typically `&str`).
  - `[T]` is unsized; use behind references/pointers (for now typically `&[T]` / `&mut [T]`).
  - Plain by-value slice usage like `[Int]` parameters is rejected in safe surface syntax.
- Lifetime elision model:
  - References have lifetimes, inferred/elided in current surface syntax.
  - Input reference parameters start with distinct inferred lifetimes unless constrained.
  - Returning a reference requires tying the return lifetime to at least one input reference.
  - Example accepted: `fn first(xs &[Int]) &Int`
  - Example rejected: `fn bad() &Int`
- Move/copy baseline:
  - Assignment, argument passing, and return are move-by-default.
  - Copy-by-default set is currently scalar numerics, `Float`, `Bool`, and shared references (`&T`).
  - Other values are move-only unless later declared copyable.
- String literal model:
  - String literals type as owned `String` values.
  - `String + String` returns `String`.
- Indexing rules:
  - `Vec<T>`, `Bytes`, and slice views index with `Int` and yield `T` (or `u8` for `Bytes`).
  - `index` operations are bounds-checked and trap/panic on out-of-bounds in safe code.
- `get(i)`-style APIs return `T | none` (`T?`) for non-trapping lookup.
- Direct indexing of `String`/`str` is rejected (UTF-8 text must be handled through byte/char APIs).
- UFCS is supported: `x.f(a, b)` desugars to `f(x, a, b)` when `f` resolves as a free function.
- Safety guarantees: undefined identifiers rejected; arity/type mismatches rejected in semantic pass.

## Safe/unsafe boundary
- `unsafe fn` and `unsafe { ... }` mark operations that are outside the safe surface contract.
- Calling an `unsafe fn` is only legal from unsafe context.
- Safety violations in checked operations trap at runtime rather than invoking undefined behavior.

## Concurrency model
- Current task model is eager/runtime-backed and does not guarantee parallel execution.
- `spawn` evaluates a callable and stores its result under a task id; `join` retrieves that result.
- `await` lowers through runtime helper behavior (`await_result`) rather than a language-level event-loop contract.
- `spawn` enforces `Send`-like constraints on argument/return types in safe code.
- Shared references passed across tasks require `Sync`-like compatibility of their pointee type.

## Modules and packages
- File module = one `.astra` file.
- Package root is directory with `Astra.toml`.
- Dependency lockfile `Astra.lock` provides reproducible resolution.
- Import forms:
  - module import: `import std.io;` (preferred) or `import stdlib::io;` (legacy)
  - string/path import: `import "relative/path";`
- Module import resolution:
  - `std.*` / `stdlib::*` resolve from stdlib root
  - other module paths resolve from nearest package root (`Astra.toml`) when present
  - if no package root is found, module paths resolve relative to importing file directory
- String/path import resolution:
  - absolute paths resolve as-is
  - relative paths resolve from the importing file directory
- Stdlib root lookup order:
  - `ASTRA_STDLIB_PATH` environment override
  - repository `stdlib/` (dev checkout)
  - bundled package path (`astra/stdlib`)

## Error handling
- Recoverable errors are modeled with unions (`Value | ErrorType`).
- Unrecoverable errors produce panic with stack trace.

## Intentional differences from Rust
- `defer expr;` schedules cleanup/action at scope exit with straightforward control-flow semantics.
- `a ?? b` is defined over nullable unions (`T | none`).
- `fn` supports compile-time specialization with most-specific implementation selection.
- `comptime { ... }` executes deterministic, pure code during compilation.
- Freestanding mode (`--freestanding`) allows hosted-runtime-free compilation flows for kernels/boot/runtime code.

## FFI
- C ABI boundary uses generated shim signatures.
- Primitive scalars map directly; strings use pointer+length pairs.


## Runtime intrinsics
- `alloc(n)` allocates `n` bytes in the managed runtime heap and returns an integer handle.
- `free(ptr)` releases a previously allocated handle.
- `spawn(fn, ...)` evaluates `fn` with provided arguments and stores the result under an integer task id.
- `join(task_id)` returns a previously stored task result.
- `countOnes(x)`, `leadingZeros(x)`, `trailingZeros(x)` (and aliases `popcnt`, `clz`, `ctz`) require integer arguments.
- `rotl(x, n)` and `rotr(x, n)` rotate integer bit patterns with modulo-width counts.
