# Unsafe

Unsafe code is explicit and opt-in.

Forms:

- `unsafe fn ...`
- `unsafe { ... }`

Rules:

- calling unsafe functions requires unsafe context
- casts involving `Any` and reference/function-pointer categories may require unsafe context

Unsafe does not disable parser/type checks; it permits operations outside safe surface restrictions.
