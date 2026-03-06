# Generics

Astra supports parametric generics on declarations such as:

- `fn id<T>(x T) T{ ... }`
- `struct Pair<T, U> { left T, right U }`

Type arguments are checked by semantic analysis using declaration signatures and specialization matching.

Related docs:

- `docs/language/types.md`
- `docs/compiler/type_system.md`
