# Astra Formal Language Specification

## Syntax

Grammar (EBNF):

```
program   = { import_decl | type_decl | struct_decl | enum_decl | extern_fn | fn_decl | impl_fn } ;
fn_decl   = ["pub"] ["async"] "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] [","] ")" "->" type block ;
impl_fn   = ["pub"] "impl" ["async"] "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] [","] ")" "->" type block ;
extern_fn = ["unsafe"] "extern" string "fn" ident "(" [param {"," param}] ")" "->" type ";" ;
param     = ident ":" type ;
type      = postfix_type ;
postfix_type = primary_type ["?"] ;
primary_type = ident ["<" type {"," type} ">"]
             | "&" ["mut"] type
             | "[" type "]"
             | "fn" "(" [type {"," type}] ")" "->" type
             | "(" type ")" ;
block     = "{" { stmt } "}" ;
stmt      = let_stmt | fixed_stmt | comptime_stmt | defer_stmt | drop_stmt | return_stmt | if_stmt | while_stmt | for_stmt | match_stmt | assign_stmt | expr ";" ;
comptime_stmt = "comptime" block ;
let_stmt  = "let" ["mut"] ident [":" type] "=" expr ";" ;
fixed_stmt = "fixed" ident [":" type] "=" expr ";" ;
defer_stmt = "defer" expr ";" ;
drop_stmt = "drop" expr ";" ;
return_stmt = "return" [expr] ";" ;
if_stmt   = "if" expr block ["else" block] ;
while_stmt = "while" expr block ;
for_stmt  = "for" (ident "in" expr | [let_stmt | fixed_stmt | expr ";"] [expr] ";" [assign_stmt | expr]) block ;
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
postfix_expr = atom { "." ident | "[" expr "]" | "(" [expr {"," expr}] ")" } ;
atom      = int | float | string | typed_int | "none" | ident | "(" expr ")" | layout_query | type_query ;
typed_int = int int_type_tok ;
int_type_tok = ("i" | "u") nonzero_digit {digit} ;
layout_query = "sizeof" "(" type ")" | "alignof" "(" type ")" | "size_of" "(" expr ")" | "align_of" "(" expr ")" ;
type_query = "bitSizeOf" "(" type ")" | "maxVal" "(" type ")" | "minVal" "(" type ")" ;
```

Conventions:
- Canonical style uses colon-typed declarations (`name: Type`) for params, fields, and local bindings.
- The parser still accepts legacy field/param style (`name Type`) for backward compatibility.
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
- Signed `i1` is rejected in semantic analysis with a hint suggesting `u1`.
- Invalid widths like `i0` or `u65536` are lexer errors.
- Built-in generic sums: `Option<T>` and `Result<T, E>`.
- Stdlib core owned types: `String`, `Vec<T>`.
- Built-in bytes alias: `Bytes = Vec<u8>`.
- Built-in unsized DSTs: `str`, `[T]`.
- Parametric generics on function declarations (`fn id<T>(x T) -> T`).
- `T?` is syntax sugar for `Option<T>`.
- `none` has no standalone type; it is valid only where `Option<T>` is expected.
- `a ?? b` requires `a: Option<T>` and `b: T`, producing `T`.
- `??` is short-circuiting: the right operand is evaluated only when the left operand is `none`.
- Integer type queries:
  - `bitSizeOf(T)` returns logical bit width.
  - `maxVal(T)`/`minVal(T)` return integer bounds for integer type `T`.
- Width-aware integer bit intrinsics:
  - `countOnes(x)`, `leadingZeros(x)`, `trailingZeros(x)`.
- `Option<T>` models absence/presence; `Result<T, E>` models recoverable failures with error information.
- `Never` is coercible to any type `T` (including `Void`).
- In type joins, `Never` acts as bottom: `join(Never, T) = T` and `join(Never, Never) = Never`.
- Bare expression statements must have type `Void` or `Never`.
- `drop expr;` consumes the value and runs its destructor immediately.
- Use `let _ = expr;` (or `_ = expr;`) to ignore/discard expression results.
- `return;` is valid only in functions returning `Void`.
- Unsized rules:
  - `str` is unsized; use behind references/pointers (for now typically `&str`).
  - `[T]` is unsized; use behind references/pointers (for now typically `&[T]` / `&mut [T]`).
  - Plain by-value slice usage like `[Int]` parameters is rejected in safe surface syntax.
- Lifetime elision model:
  - References have lifetimes, inferred/elided in current surface syntax.
  - Input reference parameters start with distinct inferred lifetimes unless constrained.
  - Returning a reference requires tying the return lifetime to at least one input reference.
  - Example accepted: `fn first(xs: &[Int]) -> &Int`
  - Example rejected: `fn bad() -> &Int`
- Move/copy baseline:
  - Assignment, argument passing, and return are move-by-default.
  - Copy-by-default set is currently scalar numerics, `Float`, `Bool`, and shared references (`&T`).
  - Other values are move-only unless later declared copyable.
- String literal model:
  - String literals conceptually type as `&'static str` (lifetime syntax currently elided in source).
- Indexing rules:
  - `Vec<T>`, `Bytes`, and slice views index with `Int` and yield `T` (or `u8` for `Bytes`).
  - `index` operations are bounds-checked and trap/panic on out-of-bounds in safe code.
  - `get(i)`-style APIs return `Option<T>` (`T?`) for non-trapping lookup.
  - Direct indexing of `String`/`str` is rejected (UTF-8 text must be handled through byte/char APIs).
- Safety guarantees: undefined identifiers rejected; arity/type mismatches rejected in semantic pass.

## Concurrency model
- M:N runtime scheduling model conceptually.
- `spawn` creates concurrent tasks and returns a task id; `join` waits for completion and yields the task result.
- Async operations are poll-based and integrate with runtime event loop.

## Modules and packages
- File module = one `.astra` file.
- Package root is directory with `Astra.toml`.
- Dependency lockfile `Astra.lock` provides reproducible resolution.

## Error handling
- Recoverable errors returned as result values.
- Unrecoverable errors produce panic with stack trace.

## Intentional differences from Rust
- `defer expr;` schedules cleanup/action at scope exit with straightforward control-flow semantics.
- `a ?? b` is defined over `Option<T>` instead of a null type.
- `impl fn` supports compile-time specialization with most-specific implementation selection.
- `comptime { ... }` executes deterministic, pure code during compilation.
- Freestanding mode (`--freestanding`) allows hosted-runtime-free compilation flows for kernels/boot/runtime code.

## FFI
- C ABI boundary uses generated shim signatures.
- Primitive scalars map directly; strings use pointer+length pairs.


## Runtime intrinsics
- `alloc(n)` allocates `n` bytes in the managed runtime heap and returns an integer handle.
- `free(ptr)` releases a previously allocated handle.
- `spawn(fn, ...)` starts `fn` on a runtime thread and returns an integer task id.
- `join(task_id)` blocks until the task completes and returns its result.
- `countOnes(x)`, `leadingZeros(x)`, `trailingZeros(x)` require integer arguments.
