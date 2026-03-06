# Functions

## Declaration Forms

- Regular: `fn add(a Int, b Int) Int{ ... }`
- Public: `pub fn ...`
- Async: `async fn ...`
- Unsafe: `unsafe fn ...`
- Overloads: multiple `fn` with the same name and different parameter types

## Returns

- Explicit `return expr;`
- `return;` only in `Void` functions
- Non-`Void` functions may return by trailing expression
- Omitted return type means `Void`

## Parameters

Function parameters use `name Type`.

## Calls

Calls are left-to-right evaluated. Arity and type checks occur during semantic analysis.
UFCS is supported: `x.f(a, b)` desugars to `f(x, a, b)`.
