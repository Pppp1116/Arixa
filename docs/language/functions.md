# Functions

## Declaration Forms

- Regular: `fn add(a Int, b Int) -> Int { ... }`
- Public: `pub fn ...`
- Async: `async fn ...`
- Unsafe: `unsafe fn ...`
- Implementation-specialized: `impl fn ...`

## Returns

- Explicit `return expr;`
- `return;` only in `-> Void` functions
- `main` may omit explicit `-> Int` in specific top-level forms

## Parameters

Preferred style is `name: Type`. Legacy `name Type` remains parser-compatible in some contexts.

## Calls

Calls are left-to-right evaluated. Arity and type checks occur during semantic analysis.
