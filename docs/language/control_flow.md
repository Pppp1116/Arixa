# Control Flow

## Branching

- `if` / `else`
- `match`

## Loops

- `while condition { ... }`
- `for item in iterable { ... }`

Supported `for` iterables:

- ranges (`start..end`, `start..=end`)
- `Vec<T>`
- slices (`&[T]`, `&mut [T]`)
- `Bytes`

## Scope Exit Helpers

- `defer expr;`
- `drop expr;`
