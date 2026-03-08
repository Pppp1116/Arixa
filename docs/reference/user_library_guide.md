# ASTRA User Libraries Guide

## Creating User Libraries

### 1. Package Structure

```
my_library/
├── Astra.toml              # Package manifest
├── src/
│   ├── lib.arixa           # Library entry point
│   ├── utils.arixa         # Additional modules
│   └── subfolder/
│       └── more.arixa      # Nested modules
├── examples/
│   └── demo.arixa          # Usage examples
└── tests/
    └── test_lib.arixa      # Test files
```

### 2. Package Manifest (Astra.toml)

```toml
[module]
name = "my_library"
version = "1.0.0"
description = "My awesome ASTRA library"
authors = ["Your Name <you@example.com>"]
license = "MIT"
homepage = "https://github.com/user/my_library"

[dependencies]
std = "1.0.0"
other_lib = "2.1.0"

[targets]
freestanding = true  # Can be used without runtime
gpu = false         # GPU support not required

[features]
default = ["core", "math"]
core = []
math = ["core"]
advanced = ["math", "external_dep"]
```

### 3. Library Entry Point

```astra
// src/lib.arixa
/// My awesome library

import std.core;
import std.math;

// Public API functions
fn my_function(x Int, y Int) Int {
    return x + y;
}

// Constants
MY_CONSTANT = 42;
```

## Using User Libraries

### 1. Local Usage

```astra
// In your main project
import "../path/to/my_library/src/lib.arixa";

fn main() Int {
    result = my_function(10, 20);
    return result + MY_CONSTANT;
}
```

### 2. Package Usage (Future)

```astra
// Once module management is implemented
import my_library;

fn main() Int {
    result = my_function(10, 20);
    return result + MY_CONSTANT;
}
```

## Comparison with Rust Crates

### Similarities

| Feature | Rust Crates | ASTRA Libraries |
|---------|-------------|------------------|
| Package manifest | Cargo.toml | Astra.toml |
| Registry | crates.io | registry/modules.json |
| Dependencies | [dependencies] | [dependencies] |
| Features | [features] | [features] |
| Examples | examples/ | examples/ |
| Tests | tests/ | tests/ |

### Key Differences

| Aspect | Rust | ASTRA |
|--------|------|-------|
| Module visibility | `pub` keyword | All public by default |
| Module qualification | `crate::module::func` | Direct access: `func()` |
| Import syntax | `use crate::module` | `import "module.arixa"` |
| Private modules | Default private | No private modules yet |
| Macro system | Procedural macros | Not implemented yet |

## Package Management Commands (Planned)

```bash
# Create new library
astra new --lib my_library

# Add dependency
astra add my_library

# Build library
astra build --lib

# Publish to registry
astra publish

# Install from registry
astra install my_library

# Update dependencies
astra update
```

## Current Status

### ✅ Working
- Basic module structure with Astra.toml
- Local file imports
- Stdlib integration
- Cross-module type checking

### 🚧 In Development
- Package manager commands
- Registry publishing
- Dependency resolution
- Version management
- Private/public visibility

### 🔄 Future Plans
- Module qualification support
- Conditional compilation
- Build profiles
- Documentation generation
- Automated testing integration

## Best Practices

### 1. Library Design
- Keep functions focused and single-purpose
- Use descriptive names
- Provide examples in documentation
- Consider freestanding compatibility

### 2. Module Organization
- Group related functionality
- Use meaningful file names
- Avoid deep nesting
- Keep entry point simple

### 3. Dependencies
- Minimize external dependencies
- Specify version ranges
- Document required features
- Test with minimal stdlib

### 4. Versioning
- Follow semantic versioning
- Document breaking changes
- Maintain backward compatibility
- Use feature flags for optional functionality

## Example: Complete Library

```astra
// src/lib.arixa
/// Advanced string processing library

import std.core;
import std.str;

// String manipulation functions
fn split_string(s String, delimiter String) Vec<String> {
    // Implementation
    return [];
}

fn join_string(parts Vec<String>, delimiter String) String {
    // Implementation
    return "";
}

fn trim_string(s String) String {
    // Implementation
    return s;
}

// Pattern matching utilities
fn matches_pattern(s String, pattern String) Bool {
    // Implementation
    return false;
}

// Constants
DEFAULT_DELIMITER = ",";
MAX_STRING_LENGTH = 1024;
```

This library can be used as:

```astra
import "../my_string_lib/src/lib.arixa";

fn process_data() Int {
    parts = split_string("a,b,c", DEFAULT_DELIMITER);
    joined = join_string(parts, "|");
    return 0;
}
```

## Conclusion

ASTRA libraries provide a foundation similar to Rust crates but with some key differences in the import system and visibility controls. While the module management ecosystem is still developing, the core functionality for creating and using user libraries is operational and continues to improve.
