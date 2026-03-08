# Any Type System Optimization

## Overview

ASTRA's `Any` type system has been optimized to be an **opt-in runtime feature** that only incurs overhead when actually used by the program. This optimization ensures that:

- **Typed programs** have zero Any runtime overhead
- **Any support** is only included when explicitly needed
- **Typed containers** are completely separate from dynamic Any-based containers
- **Normal operations** never route through Any unnecessarily

## Key Benefits

### Performance
- **Zero overhead** for typed programs - no Any runtime code included
- **Smaller binaries** - unused Any functions are compiled out
- **Faster compilation** - less code to compile and optimize

### Safety & Clarity
- **Explicit opt-in** - Any usage is clearly tracked and detected
- **Better error messages** - guides users toward typed alternatives
- **Clean separation** - typed and dynamic code paths are distinct

## How It Works

### Automatic Detection
The compiler automatically detects Any usage during semantic analysis:

```astra
// This program WILL NOT include Any runtime
fn main() Int {
    x = 42
    y = x * 2
    return y  // Purely typed operations
}
```

```astra
// This program WILL include Any runtime
fn main() Int {
    mut list = list_new()  // Uses dynamic Any-based list
    list_push(list, 42)
    list_push(list, "hello")
    return 0
}
```

### Conditional Compilation
The Any runtime is conditionally compiled using the `ASTRA_ENABLE_ANY_RUNTIME` flag:

- **No Any usage**: Flag not set → Any functions compiled out
- **Any usage detected**: Flag set → Full Any runtime included

### Build System Integration
The build system automatically:
1. Analyzes the program for Any usage
2. Sets the appropriate compiler flags
3. Links only the needed runtime components

## Any Usage Detection

The compiler tracks these Any-related patterns:

### Dynamic Containers
```astra
// Triggers Any runtime
mut list = list_new()      // Any-based list
mut map = map_new()        // Any-based map
```

### Any Type Usage
```astra
// Triggers Any runtime
value: Any = 42
any_value = some_int as Any
```

### Any Casting
```astra
// Triggers Any runtime
typed_value = any_value as Int
back_to_any = typed_value as Any
```

## Typed vs Dynamic Containers

### Typed Containers (Preferred)
```astra
// No Any runtime overhead
mut numbers: Vec<Int> = vec_new()
vec_push(numbers, 42)
first = vec_get(numbers, 0)
```

### Dynamic Any Containers (When Needed)
```astra
// Includes Any runtime
mut mixed = list_new()
list_push(mixed, 42)
list_push(mixed, "hello")
list_push(mixed, true)
```

## Performance Impact

### Binary Size Comparison
```
Typed program:     60K
Any-using program: 60K (same size in simple cases)
```

*Note: Size difference depends on actual Any usage complexity*

### Runtime Performance
- **Typed programs**: Zero Any overhead
- **Any-using programs**: Only pay for what you use

## Migration Guide

### From Any to Typed (Recommended)
```astra
// Before (Any-based)
fn process_numbers() {
    mut list = list_new()
    list_push(list, 1)
    list_push(list, 2)
    list_push(list, 3)
}

// After (Typed)
fn process_numbers() {
    mut numbers: Vec<Int> = vec_new()
    vec_push(numbers, 1)
    vec_push(numbers, 2)
    vec_push(numbers, 3)
}
```

### When to Use Any
Use Any when you need:
- **Heterogeneous collections** (mixed types in same container)
- **Dynamic typing** (types determined at runtime)
- **Interoperability** with external dynamic APIs

## Compiler Messages

### Missing Any Runtime
```
error: Any runtime function 'astra_list_new' used but Any support not required. 
Use typed containers instead.
```

### Solution
```astra
// Replace Any-based containers with typed ones
mut list: Vec<Int> = vec_new()  // Instead of list_new()
```

## Implementation Details

### AnyUsageInfo Class
Tracks Any usage patterns during compilation:
- `uses_any_type` - Any types explicitly used
- `uses_dynamic_containers` - Any-based containers used
- `uses_any_casting` - Any casting operations
- `needs_any_runtime()` - Overall Any requirement

### Conditional Compilation
```c
#if defined(ASTRA_ENABLE_ANY_RUNTIME)
// Any runtime functions
uintptr_t astra_list_new(void) { ... }
uintptr_t astra_any_box_i64(int64_t value) { ... }
// ... more Any functions
#endif
```

### Build System Flags
```bash
# No Any usage
clang -O3 -DNDEBUG program.c

# Any usage detected  
clang -O3 -DNDEBUG -DASTRA_ENABLE_ANY_RUNTIME program.c
```

## Testing

### Verification Commands
```bash
# Test Any usage detection
python -c "
from astra.semantic import analyze
from astra.parser import parse

prog = parse('fn main() Int { x = 42; return x }')
analyze(prog)
any_usage = getattr(prog, 'any_usage', None)
print('Needs Any runtime:', any_usage.needs_any_runtime())
"
```

### Test Files
- `tests/test_any_optimization.py` - Comprehensive Any optimization tests
- Tests verify detection, compilation, and runtime behavior

## Future Enhancements

### Planned Improvements
- **Better type inference** for generic containers
- **More precise detection** of minimal Any requirements
- **Performance profiling** for Any vs typed operations
- **IDE integration** for Any usage warnings

### Compatibility
- **Backward compatible**: Existing Any code continues to work
- **Opt-in optimization**: No breaking changes required
- **Gradual migration**: Can migrate to typed containers incrementally

## Best Practices

### Prefer Typed Containers
```astra
// Good - typed, no Any overhead
mut scores: Vec<Int> = vec_new()
vec_push(scores, 100)

// Avoid unless necessary
mut scores = list_new()  // Any-based
```

### Use Any Judiciously
```astra
// Appropriate Any usage
fn process_mixed_data() Any {
    mut data = list_new()
    list_push(data, get_config())     // String
    list_push(data, calculate_score()) // Int
    list_push(data, is_valid())       // Bool
    return data
}
```

### Profile When Needed
For performance-critical code, prefer typed containers and profile to verify the optimization benefits.

## Summary

The Any type system optimization provides:

✅ **Zero overhead** for typed programs  
✅ **Automatic detection** of Any requirements  
✅ **Conditional compilation** of Any runtime  
✅ **Clear migration path** to typed alternatives  
✅ **Backward compatibility** with existing code  

This makes ASTRA more efficient by default while preserving the flexibility of the Any type system when truly needed.
