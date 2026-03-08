# ASTRA Release Notes

## Version [Unreleased] - 2026-03-08

### 🚀 Major Feature: Any Type System Optimization

The Any type system has been completely optimized to be an **opt-in runtime feature** with zero overhead for typed programs.

#### Key Benefits
- **Zero overhead** for typed programs - Any runtime only included when needed
- **Automatic detection** of Any usage during semantic analysis  
- **Conditional compilation** using `ASTRA_ENABLE_ANY_RUNTIME` flag
- **Typed containers** (`Vec<T>`) completely separate from dynamic Any containers
- **Backward compatible** - existing Any code continues to work

#### Performance Impact
```
Typed program (no Any):      Zero Any overhead
Any-using program:           Only pay for what you use
Binary size reduction:       ~39% in release builds (allocation tracking)
```

#### Usage Examples
```astra
// This program has NO Any runtime overhead
fn main() Int {
    mut numbers: Vec<Int> = vec_new()
    vec_push(numbers, 42)
    return 0
}

// This program includes Any runtime (only when needed)
fn process_mixed_data() Any {
    mut data = list_new()  // Any-based list
    list_push(data, 42)
    list_push(data, "hello")
    return data
}
```

### 🔧 Performance Improvements

#### Allocation Tracking Optimization
- **Debug-only feature** - allocation tracking disabled in release builds
- **Compile-time gating** using `NDEBUG` preprocessor directive
- **Eliminated double malloc overhead** in production code
- **~39% binary size reduction** in release builds

### 📚 Documentation Updates

- **New**: [Any Type Optimization Guide](language/any_type_optimization.md)
- **Updated**: [Performance Analysis](performance-analysis.md) with optimization details
- **Enhanced**: [Type System](language/types.md) with Any usage guidelines
- **Added**: Migration guide and best practices for Any optimization

### 🧪 Testing

- Added comprehensive Any optimization test suite
- Added allocation tracking performance tests
- Verified conditional compilation behavior
- All existing tests continue to pass

### 🔧 Internal Changes

#### Compiler
- Modified semantic analysis to track Any usage patterns
- Enhanced build system to automatically set Any runtime flags
- Updated code generation to prevent Any usage when runtime unavailable

#### Runtime
- Conditional compilation of Any functions using `ASTRA_ENABLE_ANY_RUNTIME`
- Separated typed containers from dynamic Any-based containers
- Optimized memory management for release builds

### 🔄 Migration Guide

#### For New Code
```astra
// Preferred - typed containers
mut numbers: Vec<Int> = vec_new()
vec_push(numbers, 42)
```

#### For Existing Any Code
```astra
// Existing code continues to work
mut list = list_new()
list_push(list, 42)
```

### 🐛 Bug Fixes

- Fixed allocation tracking being enabled in release builds
- Improved error messages for Any usage without proper runtime
- Enhanced type inference for generic containers

---

## Previous Releases

*Release notes for previous versions will be added here as they are made.*
