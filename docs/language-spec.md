# Astra Formal Language Specification

## Syntax

Grammar (EBNF):

```
program   = { import_decl | type_decl | struct_decl | enum_decl | extern_fn | fn_decl | impl_fn } ;
fn_decl   = ["pub"] ["async"] "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] [","] ")" "->" type block ;
impl_fn   = ["pub"] "impl" ["async"] "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] [","] ")" "->" type block ;
extern_fn = ["unsafe"] "extern" string "fn" ident "(" [param {"," param}] ")" "->" type ";" ;
param     = ident ":" type ;
type      = ident
         | "&" ["mut"] type
         | "[" type "]"
         | "fn" "(" [type {"," type}] ")" "->" type
         | ident "<" type {"," type} ">" ;
block     = "{" { stmt } "}" ;
stmt      = let_stmt | fixed_stmt | comptime_stmt | defer_stmt | return_stmt | if_stmt | while_stmt | for_stmt | match_stmt | assign_stmt | expr ";" ;
comptime_stmt = "comptime" block ;
let_stmt  = "let" ["mut"] ident [":" type] "=" expr ";" ;
fixed_stmt = "fixed" ident [":" type] "=" expr ";" ;
defer_stmt = "defer" expr ";" ;
return_stmt = "return" [expr] ";" ;
if_stmt   = "if" expr block ["else" block] ;
while_stmt = "while" expr block ;
for_stmt  = "for" (ident "in" expr | [let_stmt | fixed_stmt | expr ";"] [expr] ";" [assign_stmt | expr]) block ;
assign_stmt = expr ("=" | "+=" | "-=" | "*=" | "/=" | "%=") expr ";" ;
expr      = ["await"] atom { op atom } ;
atom      = int | string | ident ["(" [expr {"," expr}] ")"] | "(" expr ")" ;
```

Conventions:
- Canonical style uses colon-typed declarations (`name: Type`) for params, fields, and local bindings.
- The parser still accepts legacy field/param style (`name Type`) for backward compatibility.

## Semantics
- Call-by-value.
- Function scope with lexical bindings.
- Strict evaluation order left-to-right.
- Integer operations are mathematically defined for non-overflowing values; implementations may trap on overflow in safe mode.

## Memory model
- Ownership-first model for user data.
- Borrowed references are immutable unless uniquely owned.
- Runtime backend uses deterministic reference counting for managed objects.

## Type system
- Nominal primitive types: `Int`, `Float`, `String`, `Bool`, `Any`, `Nil`, `Void`.
- Fixed-width integer aliases: `i8`, `u8`, `i16`, `u16`, `i32`, `u32`, `i64`, `u64`, `i128`, `u128`, `isize`, `usize`.
- Parametric generics on function declarations (`fn id<T>(x T) -> T`).
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
- `a ?? b` provides null-coalescing without verbose pattern matching for common optional fallback paths.
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
