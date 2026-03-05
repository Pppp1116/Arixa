# Types

## Built-in Primitive Families

- Integer: `Int`, `isize`, `usize`, plus `iN`/`uN` where `N` is `1..128`
- Floating: `Float`, `f32`, `f64`
- Other: `Bool`, `String`, `Any`, `Void`, `Never`

## Compound and Generic Types

- `Vec<T>`
- `Option<T>` (`T?` sugar)
- `Result<T, E>`
- references: `&T`, `&mut T`
- slices: `[T]` (unsized, usually behind references)

## Key Rules

- Integer operations require compatible integer operands.
- Explicit casts are required for narrowing or dynamic downcasts.
- `none` is only valid where `Option<T>` is expected.
- `Never` can coerce to other types in control-flow joins.
