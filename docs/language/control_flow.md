# Control Flow

## Branching

### If/Else
```astra
if condition {
    // then branch
} else if another_condition {
    // else if branch
} else {
    // else branch
}
```

### Match Expressions
```astra
match value {
    pattern1 => result1,
    pattern2 => result2,
    _ => default_result,
}
```

## Loops

### While Loops
```astra
while condition {
    // loop body
}
```

### For Loops (Iterator Style)
```astra
for item in iterable {
    // loop body
}
```

**Important**: `for` loops use iterator-style syntax (no traditional C-style for loops). The old `ForStmt` has been replaced with `IteratorForStmt`.

### Supported For Iterables

- **Ranges**: `0..10`, `1..=5`
- **Vectors**: `Vec<T>`
- **Slices**: `&[T]`, `&mut [T]`
- **Arrays**: `[T; N]`
- **Bytes**: `Bytes`
- **Strings**: `String` (character iteration)

### Loop Control

- **Break**: `break;` - exit loop immediately
- **Continue**: `continue;` - skip to next iteration

## Scope Exit Helpers

### Defer
```astra
fn example() Void {
    defer cleanup();
    // do work
    // cleanup() called automatically
}
```

## Examples

### Nested Control Flow
```astra
fn process_items(items: &[Int]) Int {
    mut result = 0;
    
    for item in items {
        if item > 0 {
            while result < item {
                result = result + 1;
            }
        } else {
            break;
        }
    }
    
    return result;
}
```

### Match with Guard
```astra
fn classify_number(n: Int) String {
    match n {
        0 => "zero",
        x if x < 0 => "negative",
        x if x > 0 => "positive",
        _ => "unknown",
    }
}
```
