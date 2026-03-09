# Types

## Built-in Primitive Types

### Integer Types
- **Default**: `Int` (canonicalizes to `i64`)
- **Signed**: `i8`, `i16`, `i32`, `i64`, `i128`, `isize`
- **Unsigned**: `u8`, `u16`, `u32`, `u64`, `u128`, `usize`
- **Special**: `Int` (default integer type, automatically converts to/from `i64`)

### Floating Point Types
- **Default**: `Float` (canonicalizes to `f64`)
- **Available**: `f16`, `f32`, `f64`, `f80`, `f128`

### Other Primitives
- **Boolean**: `Bool` (`true`, `false`)
- **String**: `String`
- **Bytes**: `Bytes`
- **Unit**: `Void`
- **Bottom**: `Never` (uninhabited type)
- **Dynamic**: `Any` - opt-in runtime feature (see [Any Type Optimization](any_type_optimization.md))

## Compound and Generic Types

### Collections
- **Vector**: `Vec<T>` - growable array
- **Array**: `[T; N]` - fixed-size array
- **Slice**: `[T]` - unsized view (usually behind references)

### References
- **Immutable**: `&T`
- **Mutable**: `&mut T`

### Union Types
- **Explicit**: `A | B | C`
- **Nullable sugar**: `T?` = `T | none`
- **Function returns**: `Int | none` for operations that may fail

### Function Types
- **Function pointer**: `fn(T) -> U`
- **Async**: `async fn(T) -> U`
- **Unsafe**: `unsafe fn(T) -> U`

## Type System Features

### Automatic Conversions
- **Int ↔ i64**: Automatic bidirectional conversion
- **Slice conversion**: `&Vec<T>` → `&[T]` automatic conversion
- **Nullable conversion**: `Int` → `Int | none` automatic conversion

### Type Inference
- **Local variables**: Type inferred from assignment
- **Function returns**: Type inferred from return expressions
- **Generic types**: Type inference for generic parameters

## Key Rules

### Integer Operations
- Integer operations require compatible integer operands
- Explicit casts required for narrowing conversions
- Widening conversions are automatic
- `Int` type provides maximum flexibility

### Nullability
- `none` is only valid where a nullable union is expected
- Use `?` syntax for nullable types: `Int?` = `Int | none`
- Coalesce operator: `value ?? default`

### References
- References must be initialized
- Mutable references cannot be aliased
- Lifetime checking enforced by compiler

### Control Flow
- `Never` can coerce to other types in control-flow joins
- `Void` is the unit type for functions that don't return values

## Examples

### Type Annotations
```astra
x: Int = 42;           // Explicit type
y = 42;               // Inferred as Int
numbers: Vec<Int> = [1, 2, 3];
slice: &[Int] = &numbers;
```

### Nullable Types
```astra
fn find_item(items: &[Int], target: Int) Int? {
    for item in items {
        if item == target {
            return item;  // Returns Int | none
        }
    }
    return none;  // Returns none
}

// Usage
result = find_item([1, 2, 3], 2) ?? 0;  // Coalesce with default
```

### Type Conversions
```astra
fn process(value: Int) i64 {
    // Automatic Int to i64 conversion
    return value;
}

fn accept_slice(data: &[Int]) Int {
    // Can pass &Vec<Int> to &[Int] parameter
    return data[0];
}

vec_data: Vec<Int> = [1, 2, 3];
first = accept_slice(&vec_data);  // Automatic conversion
```

## Any Type

The `Any` type provides dynamic typing capabilities but is **optimized to be opt-in**:

### When to Use Any
```astra
// Heterogeneous collections
fn process_mixed_data() Any {
    mut data = list_new();  // Any-based list
    list_push(data, "config");  // String
    list_push(data, 42);       // Int
    list_push(data, true);     // Bool
    return data;
}

// Dynamic casting
fn handle_any(value: Any) Int {
    if value is Int {
        return value as Int;
    }
    return 0;
}
```

### Prefer Typed Containers
```astra
// Better - no Any overhead
fn process_numbers() {
    mut numbers: Vec<Int> = vec_new();
    vec_push(numbers, 42);
    vec_push(numbers, 84);
}
```

**Note**: The Any runtime is only included when actually used. Typed programs have zero Any overhead. See [Any Type Optimization](any_type_optimization.md) for complete details.
