# Astra Formal Language Specification

## Syntax

Grammar (EBNF):

```
program   = { fn_decl } ;
fn_decl   = "fn" ident ["<" ident {"," ident} ">"] "(" [param {"," param}] ")" "->" type block ;
param     = ident type ;
type      = ident ;
block     = "{" { stmt } "}" ;
stmt      = let_stmt | return_stmt | if_stmt | while_stmt | expr ";" ;
let_stmt  = "let" ident "=" expr ";" ;
return_stmt = "return" [expr] ";" ;
if_stmt   = "if" expr block ["else" block] ;
while_stmt = "while" expr block ;
expr      = atom { op atom } ;
atom      = int | string | ident ["(" [expr {"," expr}] ")"] | "(" expr ")" ;
```

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
- Nominal primitive types: `Int`, `String`, `Bool`, `Any`.
- Parametric generics on function declarations (`fn id<T>(x T) -> T`).
- Safety guarantees: undefined identifiers rejected; arity/type mismatches rejected in semantic pass.

## Concurrency model
- M:N runtime scheduling model conceptually.
- `spawn` creates concurrent tasks; message-passing and shared immutable data are preferred.
- Async operations are poll-based and integrate with runtime event loop.

## Modules and packages
- File module = one `.astra` file.
- Package root is directory with `Astra.toml`.
- Dependency lockfile `Astra.lock` provides reproducible resolution.

## Error handling
- Recoverable errors returned as result values.
- Unrecoverable errors produce panic with stack trace.

## FFI
- C ABI boundary uses generated shim signatures.
- Primitive scalars map directly; strings use pointer+length pairs.
