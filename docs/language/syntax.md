# Syntax

## Declarations

- Functions: `fn name(args) Type{ ... }`
- Structs: `struct Name { field Type, ... }`
- Enums: `enum Name { Variant, Variant(T) }`
- Type aliases: `type Name = Existing;`
- Imports: `import std.io;` or `import "relative/path";`

## Statements

- `name = expr`, `mut name = expr`, `set name = expr`
- `if` / `else`
- `while`
- `for item in iterable { ... }`
- `match`
- `return`, `break`, `continue`, `drop`, `defer`

## Expressions

- arithmetic, logical, and bitwise operators
- casts: `expr as Type`
- coalescing: `option_value ?? fallback`
- calls/indexing/field access
- layout/type queries (`sizeof`, `alignof`, `bitSizeOf`, `maxVal`, `minVal`)
