# Performance Analysis

## Optimizations

### Any Type System Optimization
- **Zero overhead** for typed programs - Any runtime only included when needed
- **Conditional compilation** using `ASTRA_ENABLE_ANY_RUNTIME` flag
- **Automatic detection** of Any usage during semantic analysis
- **Typed containers** (`Vec<T>`) are completely separate from dynamic Any containers
- See [Any Type Optimization](language/any_type_optimization.md) for details

### Allocation Tracking Optimization
- **Debug-only feature** - allocation tracking disabled in release builds
- **Compile-time gating** using `NDEBUG` preprocessor directive
- **Eliminates double malloc overhead** in production
- **~39% binary size reduction** in release builds

### Threading Runtime Optimization
- **Lazy initialization** - threading tables only allocated on first use
- **Zero overhead** for non-threaded programs
- **Slot table architecture** replaces global linear arrays
- **O(1) operations** for spawn, mutex, and channel lookups
- **Per-channel locking** eliminates global coordination bottlenecks

### String Operations Optimization
- **StringBuilder API** for efficient string construction
- **O(n) performance** for repeated concatenation (vs O(n²) with simple concat)
- **Power-of-2 buffer growth** for amortized constant-time appends
- **Simple concat preserved** for basic use cases
- **No global string interning** - avoids hash-table overhead

### Collection Operations Optimization
- **Typed collections** with native layouts (Vec<T>, Map<K,V>)
- **Hash table implementation** for O(1) average lookups
- **Separate fast/slow paths** for typed vs dynamic collections
- **Eliminated linear scans** in collection operations

### Other Optimizations
- Constant folding optimizer reduces arithmetic overhead.
- Incremental compilation skips unchanged inputs.
- Baseline benchmark in `benchmarks/bench.py` reports build and execution timings.

## Performance Impact

### Binary Size Comparison
```
Debug build (with allocation tracking):     98K
Release build (without allocation tracking): 60K
Size reduction: ~39%
```

### Runtime Overhead Comparison
```
Non-threaded program:        Zero threading overhead
Threaded program:            O(1) threading operations
Simple string concat:         O(n) per operation
StringBuilder in loops:      O(n) total (vs O(n²) with concat)
Typed collections:            O(1) hash table lookups
Any-using program:            Only pay for what you use
```

### Memory Management
- **Release builds**: Direct malloc/free calls
- **Debug builds**: Allocation tracking with leak detection
- **Any programs**: Optional dynamic type system overhead
- **Threading**: Lazy allocation only when used
- **Strings**: Efficient buffer growth with StringBuilder

### Scalability Improvements
- **Threading**: No global locks, per-object synchronization
- **Collections**: Hash tables replace linear scans
- **Strings**: StringBuilder eliminates quadratic concatenation
- **Memory**: Slot tables prevent fragmentation

## Measurement Tools

### Benchmarking
```bash
# Run performance benchmarks
python benchmarks/bench.py

# Test allocation tracking optimization
python tests/test_allocation_tracking.py

# Test Any type optimization
python tests/test_any_optimization.py
```

### Build Profiles
```bash
# Debug profile (with allocation tracking)
astra build program.astra --profile debug

# Release profile (optimized)
astra build program.astra --profile release
```

## Performance Guidelines

### Prefer Typed Code
```astra
// Good - no Any overhead, O(1) operations
mut numbers: Vec<Int> = vec_new()
vec_push(numbers, 42)

// Use Any only when needed
mut mixed = list_new()  // Heterogeneous data
```

### Use StringBuilder for String Building
```astra
// Good - O(n) total performance
sb = StringBuilder.new()
for i in 0..1000 {
    sb.append_str("item")
    sb.append_int(i)
}
result = sb.finish()

// Avoid - O(n²) performance
result = ""
for i in 0..1000 {
    result = result + "item" + to_string_int(i)
}
```

### Use Typed Collections
```astra
// Good - O(1) hash table lookups
map: Map<String, Int> = map_new()
map_set(map, "key", 42)

// Use Any only for dynamic data
dynamic = map_new()  // Map<Any, Any>
```

### Threading Best Practices
```astra
// Threading is zero-cost until used
// No overhead for programs that don't use threads

// When using threads, operations are O(1)
handle = spawn(my_function, arg)
result = join(handle)
```

### Use Release Builds
- Always use `--profile release` for production
- Debug builds include allocation tracking overhead
- Release builds have optimized memory management

### Profile When Needed
For performance-critical applications:
1. Use typed containers consistently
2. Use StringBuilder for string construction
3. Build with release profile
4. Profile actual performance bottlenecks
5. Use Any only when dynamically typed data is required
6. Consider threading overhead - it's lazy-loaded
